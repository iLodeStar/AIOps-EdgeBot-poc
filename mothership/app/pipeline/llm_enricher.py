"""LLM-assisted enrichment with guardrails and safety measures."""
import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Union
import httpx
import structlog
from .processor import Processor

logger = structlog.get_logger()

class LLMEnricher(Processor):
    """
    LLM-assisted enrichment with strict guardrails:
    - PII pre-redacted by deterministic processors
    - Bounded instructions and JSON schema outputs
    - Confidence threshold gating
    - Fallback to deterministic-only on error/low confidence
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "LLMEnricher")
        
        self.enabled = config.get('enabled', False)
        if not self.enabled:
            logger.info("LLM enrichment is disabled")
            return
        
        # Backend selection
        self.backend = config.get('backend', 'openai').lower()
        if self.backend not in ['openai', 'ollama']:
            raise ValueError(f"Invalid LLM backend: {self.backend}. Must be 'openai' or 'ollama'")
        
        # Common configuration
        self.confidence_threshold = config.get('confidence_threshold', 0.8)
        
        # Safety limits
        self.max_event_size = config.get('max_event_size', 10000)  # chars
        self.timeout_seconds = config.get('timeout', 30)
        
        # Backend-specific configuration
        if self.backend == 'openai':
            self._init_openai_config(config)
        elif self.backend == 'ollama':
            self._init_ollama_config(config)
        
        # Circuit breaker configuration
        self.circuit_breaker_enabled = config.get('circuit_breaker', {}).get('enabled', True)
        self.failure_threshold = config.get('circuit_breaker', {}).get('failure_threshold', 5)
        self.reset_timeout = config.get('circuit_breaker', {}).get('reset_timeout', 60)
        
        # Circuit breaker state
        self.failure_count = 0
        self.last_failure_time = 0
        self.circuit_open = False
        
        # HTTP client
        self.client = None
        
        # JSON schema for LLM responses (same for both backends)
        self.response_schema = {
            "type": "object",
            "properties": {
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "tags": {
                    "type": "object",
                    "additionalProperties": {"type": "string"}
                },
                "category": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "summary": {"type": "string", "maxLength": 200}
            },
            "required": ["confidence"],
            "additionalProperties": False
        }
        
        logger.info(f"Initialized LLM enricher", 
                   backend=self.backend,
                   confidence_threshold=self.confidence_threshold,
                   model=getattr(self, 'model', 'unknown'))
    
    def _init_openai_config(self, config: Dict[str, Any]):
        """Initialize OpenAI-specific configuration."""
        self.endpoint = config.get('endpoint', 'https://api.openai.com/v1')
        self.api_key = config.get('api_key')
        self.model = config.get('model', 'gpt-3.5-turbo')
        self.max_tokens = config.get('max_tokens', 150)
        self.temperature = config.get('temperature', 0.0)
    
    def _init_ollama_config(self, config: Dict[str, Any]):
        """Initialize Ollama-specific configuration."""
        self.base_url = config.get('ollama_base_url', 'http://localhost:11434')
        self.model = config.get('ollama_model', 'llama3.1:8b-instruct-q4_0')
        self.max_tokens = config.get('ollama_max_tokens', 150)
        self.temperature = config.get('temperature', 0.0)
        
        # Convert timeout from milliseconds if provided
        timeout_ms = config.get('ollama_timeout_ms')
        if timeout_ms:
            self.timeout_seconds = timeout_ms / 1000
    
    def is_enabled(self) -> bool:
        """Override to check both config and circuit breaker state."""
        return self.enabled and not self.circuit_open
    
    async def _init_client(self):
        """Initialize HTTP client."""
        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
            )
    
    async def _close_client(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process event with LLM enrichment."""
        if not self.is_enabled():
            logger.debug("LLM enricher disabled or circuit open")
            return event
        
        # Check circuit breaker
        if self.circuit_breaker_enabled and self._should_trip_circuit():
            return event
        
        try:
            # Validate event size
            event_str = json.dumps(event)
            if len(event_str) > self.max_event_size:
                logger.warning("Event too large for LLM processing", size=len(event_str))
                return event
            
            # Initialize client if needed
            await self._init_client()
            
            # Call LLM
            llm_response = await self._call_llm(event)
            
            if llm_response and self._validate_response(llm_response):
                confidence = llm_response.get('confidence', 0.0)
                
                if confidence >= self.confidence_threshold:
                    enriched_event = self._apply_llm_enrichment(event, llm_response)
                    logger.debug("Applied LLM enrichment", confidence=confidence)
                    return enriched_event
                else:
                    logger.debug("LLM confidence below threshold", 
                               confidence=confidence, 
                               threshold=self.confidence_threshold)
            
            return event
            
        except Exception as e:
            self._record_failure()
            logger.error("LLM enrichment failed", error=str(e))
            return event
    
    async def _call_llm(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call LLM API with bounded instructions."""
        
        # Create safe prompt (no PII should be present at this point)
        prompt = self._create_safe_prompt(event)
        
        # Route to backend-specific implementation
        if self.backend == 'openai':
            return await self._call_openai_llm(prompt)
        elif self.backend == 'ollama':
            return await self._call_ollama_llm(prompt)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")
    
    async def _call_openai_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call OpenAI-compatible LLM API."""
        
        # Prepare request
        request_data = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a log analysis assistant. Analyze the provided log event and "
                        "return structured enrichment data in JSON format. "
                        "Do not include any personally identifiable information in your response. "
                        "Provide only the requested fields with appropriate confidence scores."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"}
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else None
        }
        
        # Remove None headers
        headers = {k: v for k, v in headers.items() if v is not None}
        
        try:
            response = await self.client.post(
                f"{self.endpoint}/chat/completions",
                json=request_data,
                headers=headers
            )
            response.raise_for_status()
            
            result = response.json()
            if 'choices' in result and result['choices']:
                content = result['choices'][0]['message']['content']
                return json.loads(content)
            
            return None
            
        except httpx.TimeoutException:
            logger.warning("OpenAI LLM request timeout")
            raise
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON response from OpenAI LLM", error=str(e))
            raise
        except Exception as e:
            logger.error("OpenAI LLM API call failed", error=str(e))
            raise
    
    async def _call_ollama_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call Ollama LLM API."""
        
        # Prepare system message and user prompt
        system_message = (
            "You are a log analysis assistant. Analyze the provided log event and "
            "return structured enrichment data in JSON format. "
            "Do not include any personally identifiable information in your response. "
            "Provide only the requested fields with appropriate confidence scores."
        )
        
        # Use chat endpoint for better conversation support
        request_data = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_message
                },
                {
                    "role": "user",  
                    "content": prompt
                }
            ],
            "stream": False,
            "format": "json",  # Request JSON format response
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature
            }
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                headers=headers
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Ollama chat response format
            if 'message' in result and 'content' in result['message']:
                content = result['message']['content']
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # If content is not valid JSON, try to extract JSON from it
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                    else:
                        logger.warning("No valid JSON found in Ollama response", content=content)
                        return None
            
            return None
            
        except httpx.TimeoutException:
            logger.warning("Ollama LLM request timeout")
            raise
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON response from Ollama LLM", error=str(e))
            raise
        except Exception as e:
            logger.error("Ollama LLM API call failed", error=str(e))
            raise
    
    def _create_safe_prompt(self, event: Dict[str, Any]) -> str:
        """Create a safe prompt with bounded context."""
        
        # Extract key fields for analysis (PII should already be redacted)
        safe_fields = {}
        
        # Include only safe fields
        safe_field_names = [
            'type', 'severity', 'facility', 'tag', 'service', 
            'hostname', 'message', 'category', 'tags'
        ]
        
        for field in safe_field_names:
            if field in event and event[field]:
                safe_fields[field] = event[field]
        
        # Truncate message if too long
        if 'message' in safe_fields and len(str(safe_fields['message'])) > 500:
            safe_fields['message'] = str(safe_fields['message'])[:500] + "..."
        
        prompt = f"""
Analyze this log event and provide enrichment data:

Event: {json.dumps(safe_fields, indent=2)}

Respond with JSON containing:
- confidence: float 0.0-1.0 (how confident you are in the analysis)
- tags: object with key-value pairs for additional context
- category: string describing the event category
- priority: one of "low", "medium", "high", "critical"
- summary: brief description (max 200 chars)

Example response:
{{
    "confidence": 0.9,
    "tags": {{"component": "database", "action": "connection"}},
    "category": "system_event",
    "priority": "medium",
    "summary": "Database connection established successfully"
}}
"""
        
        return prompt.strip()
    
    def _validate_response(self, response: Dict[str, Any]) -> bool:
        """Validate LLM response against schema."""
        try:
            # Basic structure validation
            if not isinstance(response, dict):
                return False
            
            # Required fields
            if 'confidence' not in response:
                return False
            
            confidence = response['confidence']
            if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
                return False
            
            # Optional fields validation
            if 'tags' in response:
                if not isinstance(response['tags'], dict):
                    return False
                # Check all tag values are strings
                for k, v in response['tags'].items():
                    if not isinstance(v, str):
                        return False
            
            if 'priority' in response:
                if response['priority'] not in ['low', 'medium', 'high', 'critical']:
                    return False
            
            if 'summary' in response:
                if not isinstance(response['summary'], str) or len(response['summary']) > 200:
                    return False
            
            return True
            
        except Exception as e:
            logger.warning("Response validation failed", error=str(e))
            return False
    
    def _apply_llm_enrichment(self, event: Dict[str, Any], llm_response: Dict[str, Any]) -> Dict[str, Any]:
        """Apply LLM enrichment to event."""
        enriched_event = event.copy()
        
        # Add LLM metadata
        enriched_event['llm_enrichment'] = {
            'model': self.model,
            'confidence': llm_response['confidence'],
            'timestamp': time.time()
        }
        
        # Apply LLM tags
        if 'tags' in llm_response:
            if 'tags' not in enriched_event:
                enriched_event['tags'] = {}
            
            # Add LLM tags with prefix to distinguish from deterministic ones
            for key, value in llm_response['tags'].items():
                enriched_event['tags'][f"llm_{key}"] = value
        
        # Apply other enrichments
        if 'category' in llm_response:
            enriched_event['llm_category'] = llm_response['category']
        
        if 'priority' in llm_response:
            enriched_event['llm_priority'] = llm_response['priority']
        
        if 'summary' in llm_response:
            enriched_event['llm_summary'] = llm_response['summary']
        
        return enriched_event
    
    def _record_failure(self):
        """Record a failure for circuit breaker."""
        if self.circuit_breaker_enabled:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.circuit_open = True
                logger.warning("LLM circuit breaker tripped", 
                             failure_count=self.failure_count)
    
    def _should_trip_circuit(self) -> bool:
        """Check if circuit breaker should be tripped."""
        if not self.circuit_open:
            return False
        
        # Check if reset timeout has passed
        if time.time() - self.last_failure_time > self.reset_timeout:
            self.circuit_open = False
            self.failure_count = 0
            logger.info("LLM circuit breaker reset")
            return False
        
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get enhanced stats including circuit breaker state."""
        stats = super().get_stats()
        stats.update({
            'enabled': self.enabled,
            'backend': getattr(self, 'backend', 'unknown'),
            'circuit_open': self.circuit_open,
            'failure_count': self.failure_count,
            'confidence_threshold': self.confidence_threshold
        })
        return stats
    
    async def cleanup(self):
        """Cleanup resources."""
        await self._close_client()


class MockLLMEnricher(LLMEnricher):
    """Mock LLM enricher for testing."""
    
    def __init__(self, config: Dict[str, Any]):
        # Initialize parent but don't create HTTP client
        super().__init__(config)
        self.mock_responses = config.get('mock_responses', [])
        self.response_index = 0
    
    async def _call_llm(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return mock response."""
        if not self.mock_responses:
            # Default mock response
            return {
                "confidence": 0.9,
                "tags": {"component": "test", "enriched": "true"},
                "category": "test_event",
                "priority": "medium",
                "summary": "Mock enrichment for testing"
            }
        
        # Cycle through mock responses
        response = self.mock_responses[self.response_index % len(self.mock_responses)]
        self.response_index += 1
        return response
    
    async def _init_client(self):
        """No-op for mock."""
        pass
    
    async def _close_client(self):
        """No-op for mock."""
        pass