"""Tests for LLM enricher."""
import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import json
import sys
import os
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))

from pipeline.llm_enricher import LLMEnricher, MockLLMEnricher

class TestMockLLMEnricher(unittest.TestCase):
    """Test mock LLM enricher for testing scenarios."""
    
    def test_mock_llm_disabled(self):
        """Test mock LLM when disabled."""
        config = {'enabled': False}
        enricher = MockLLMEnricher(config)
        
        event = {'message': 'Test event', 'type': 'log'}
        result = asyncio.run(enricher.process(event))
        
        # Should return unchanged when disabled
        self.assertEqual(result, event)
    
    def test_mock_llm_enabled_default_response(self):
        """Test mock LLM with default response."""
        config = {
            'enabled': True,
            'confidence_threshold': 0.8
        }
        enricher = MockLLMEnricher(config)
        
        event = {'message': 'Test event', 'type': 'log'}
        result = asyncio.run(enricher.process(event))
        
        # Should add LLM enrichment
        self.assertIn('llm_enrichment', result)
        self.assertEqual(result['llm_enrichment']['confidence'], 0.9)
        self.assertIn('tags', result)
        self.assertEqual(result['tags']['llm_component'], 'test')
        self.assertEqual(result['llm_category'], 'test_event')
        self.assertEqual(result['llm_priority'], 'medium')
    
    def test_mock_llm_custom_responses(self):
        """Test mock LLM with custom responses."""
        mock_responses = [
            {
                'confidence': 0.95,
                'tags': {'component': 'database', 'action': 'query'},
                'category': 'database_event',
                'priority': 'high',
                'summary': 'Database query executed'
            },
            {
                'confidence': 0.7,  # Below threshold
                'tags': {'component': 'web'},
                'category': 'web_event',
                'priority': 'low'
            }
        ]
        
        config = {
            'enabled': True,
            'confidence_threshold': 0.8,
            'mock_responses': mock_responses
        }
        enricher = MockLLMEnricher(config)
        
        # First event - high confidence, should be enriched
        event1 = {'message': 'Database query', 'type': 'log'}
        result1 = asyncio.run(enricher.process(event1))
        
        self.assertIn('llm_enrichment', result1)
        self.assertEqual(result1['llm_enrichment']['confidence'], 0.95)
        self.assertEqual(result1['tags']['llm_component'], 'database')
        self.assertEqual(result1['llm_category'], 'database_event')
        
        # Second event - low confidence, should not be enriched
        event2 = {'message': 'Web request', 'type': 'log'}
        result2 = asyncio.run(enricher.process(event2))
        
        # Should not have LLM enrichment due to low confidence
        self.assertNotIn('llm_enrichment', result2)
        self.assertNotIn('llm_category', result2)
    
    def test_mock_llm_response_validation(self):
        """Test response validation."""
        # Invalid response (missing confidence)
        invalid_responses = [
            {
                'tags': {'component': 'test'},
                'category': 'test_event'
                # Missing confidence
            }
        ]
        
        config = {
            'enabled': True,
            'mock_responses': invalid_responses
        }
        enricher = MockLLMEnricher(config)
        
        event = {'message': 'Test event', 'type': 'log'}
        result = asyncio.run(enricher.process(event))
        
        # Should return original event due to validation failure
        self.assertEqual(result, event)


class TestLLMEnricher(unittest.TestCase):
    """Test real LLM enricher (with mocked HTTP calls)."""
    
    def test_llm_disabled(self):
        """Test LLM enricher when disabled."""
        config = {'enabled': False}
        enricher = LLMEnricher(config)
        
        event = {'message': 'Test event', 'type': 'log'}
        result = asyncio.run(enricher.process(event))
        
        # Should return unchanged when disabled
        self.assertEqual(result, event)
    
    @patch('httpx.AsyncClient.post')
    async def test_llm_successful_enrichment(self, mock_post):
        """Test successful LLM enrichment."""
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        'confidence': 0.9,
                        'tags': {'component': 'auth', 'action': 'login'},
                        'category': 'authentication',
                        'priority': 'medium',
                        'summary': 'User authentication attempt'
                    })
                }
            }]
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'endpoint': 'https://api.openai.com/v1',
            'api_key': 'test-key',
            'model': 'gpt-3.5-turbo',
            'confidence_threshold': 0.8
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'User login attempt', 'type': 'syslog'}
        result = await enricher.process(event)
        
        # Should be enriched
        self.assertIn('llm_enrichment', result)
        self.assertEqual(result['llm_enrichment']['confidence'], 0.9)
        self.assertEqual(result['tags']['llm_component'], 'auth')
        self.assertEqual(result['llm_category'], 'authentication')
        
        # Verify HTTP call was made
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('chat/completions', call_args[0][0])
        self.assertEqual(call_args[1]['headers']['Authorization'], 'Bearer test-key')
    
    @patch('httpx.AsyncClient.post')
    async def test_llm_low_confidence_rejection(self, mock_post):
        """Test rejection of low confidence responses."""
        # Mock HTTP response with low confidence
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        'confidence': 0.6,  # Below threshold
                        'tags': {'component': 'unknown'},
                        'category': 'unknown'
                    })
                }
            }]
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'confidence_threshold': 0.8,
            'api_key': 'test-key'
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'Unclear log message', 'type': 'log'}
        result = await enricher.process(event)
        
        # Should not be enriched due to low confidence
        self.assertNotIn('llm_enrichment', result)
        self.assertNotIn('llm_category', result)
    
    def test_event_size_limit(self):
        """Test event size limiting."""
        config = {
            'enabled': True,
            'max_event_size': 100  # Very small limit
        }
        enricher = LLMEnricher(config)
        
        # Large event
        large_event = {
            'message': 'x' * 200,  # Exceeds limit
            'type': 'log'
        }
        
        result = asyncio.run(enricher.process(large_event))
        
        # Should return unchanged due to size limit
        self.assertEqual(result, large_event)
    
    def test_circuit_breaker(self):
        """Test circuit breaker functionality."""
        config = {
            'enabled': True,
            'circuit_breaker': {
                'enabled': True,
                'failure_threshold': 2,
                'reset_timeout': 60
            }
        }
        enricher = LLMEnricher(config)
        
        # Simulate failures to trip circuit breaker
        enricher.failure_count = 2
        enricher.circuit_open = True
        enricher.last_failure_time = asyncio.get_event_loop().time()
        
        event = {'message': 'Test event', 'type': 'log'}
        result = asyncio.run(enricher.process(event))
        
        # Should return unchanged due to open circuit
        self.assertEqual(result, event)
    
    def test_response_validation(self):
        """Test LLM response validation."""
        config = {'enabled': True}
        enricher = LLMEnricher(config)
        
        # Valid response
        valid_response = {
            'confidence': 0.9,
            'tags': {'component': 'test'},
            'category': 'test_event',
            'priority': 'medium'
        }
        self.assertTrue(enricher._validate_response(valid_response))
        
        # Invalid responses
        invalid_responses = [
            {'tags': {'test': 'value'}},  # Missing confidence
            {'confidence': 1.5},  # Invalid confidence range
            {'confidence': 0.8, 'tags': {'test': 123}},  # Non-string tag value
            {'confidence': 0.8, 'priority': 'invalid'},  # Invalid priority
            {'confidence': 0.8, 'summary': 'x' * 300}  # Summary too long
        ]
        
        for invalid_response in invalid_responses:
            with self.subTest(response=invalid_response):
                self.assertFalse(enricher._validate_response(invalid_response))
    
    def test_safe_prompt_creation(self):
        """Test creation of safe prompts."""
        config = {'enabled': True}
        enricher = LLMEnricher(config)
        
        event = {
            'message': 'User login failed',
            'type': 'syslog',
            'severity': 'error',
            'service': 'auth',
            'hostname': 'web01',
            'password': 'should_not_appear',  # Should be ignored
            'internal_id': 'should_not_appear'  # Should be ignored
        }
        
        prompt = enricher._create_safe_prompt(event)
        
        # Should include safe fields
        self.assertIn('User login failed', prompt)
        self.assertIn('syslog', prompt)
        self.assertIn('error', prompt)
        self.assertIn('auth', prompt)
        
        # Should not include unsafe fields
        self.assertNotIn('password', prompt)
        self.assertNotIn('should_not_appear', prompt)
    
    def test_get_enhanced_stats(self):
        """Test enhanced statistics."""
        config = {
            'enabled': True,
            'confidence_threshold': 0.8
        }
        enricher = LLMEnricher(config)
        
        stats = enricher.get_stats()
        
        self.assertIn('enabled', stats)
        self.assertIn('circuit_open', stats)
        self.assertIn('failure_count', stats)
        self.assertIn('confidence_threshold', stats)
        self.assertEqual(stats['enabled'], True)
        self.assertEqual(stats['confidence_threshold'], 0.8)


class TestOllamaLLMEnricher(unittest.TestCase):
    """Test Ollama LLM enricher with mocked HTTP calls."""
    
    @patch('httpx.AsyncClient.post')
    async def test_ollama_successful_enrichment(self, mock_post):
        """Test successful Ollama LLM enrichment."""
        # Mock Ollama response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'message': {
                'content': json.dumps({
                    'confidence': 0.85,
                    'tags': {'component': 'web', 'action': 'request'},
                    'category': 'web_access',
                    'priority': 'low',
                    'summary': 'Web request processed'
                })
            }
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'backend': 'ollama',
            'ollama_base_url': 'http://localhost:11434',
            'ollama_model': 'llama3.1:8b-instruct-q4_0',
            'confidence_threshold': 0.8
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'GET /api/users HTTP/1.1', 'type': 'access_log'}
        result = await enricher.process(event)
        
        # Should be enriched
        self.assertIn('llm_enrichment', result)
        self.assertEqual(result['llm_enrichment']['confidence'], 0.85)
        self.assertEqual(result['tags']['llm_component'], 'web')
        self.assertEqual(result['llm_category'], 'web_access')
        
        # Verify HTTP call was made to Ollama
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('/api/chat', call_args[0][0])
        
        # Check request structure
        request_data = call_args[1]['json']
        self.assertEqual(request_data['model'], 'llama3.1:8b-instruct-q4_0')
        self.assertFalse(request_data['stream'])
        self.assertEqual(request_data['format'], 'json')
        self.assertIn('messages', request_data)
        self.assertEqual(len(request_data['messages']), 2)  # system + user
    
    @patch('httpx.AsyncClient.post')
    async def test_ollama_low_confidence_rejection(self, mock_post):
        """Test rejection of low confidence Ollama responses."""
        # Mock Ollama response with low confidence
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'message': {
                'content': json.dumps({
                    'confidence': 0.6,  # Below threshold
                    'tags': {'component': 'unknown'},
                    'category': 'unknown'
                })
            }
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'backend': 'ollama',
            'confidence_threshold': 0.8
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'Unclear log message', 'type': 'log'}
        result = await enricher.process(event)
        
        # Should not be enriched due to low confidence
        self.assertNotIn('llm_enrichment', result)
        self.assertNotIn('llm_category', result)
    
    @patch('httpx.AsyncClient.post')
    async def test_ollama_malformed_json_extraction(self, mock_post):
        """Test extraction of JSON from malformed Ollama responses."""
        # Mock Ollama response with text around JSON
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'message': {
                'content': 'Here is the analysis: {"confidence": 0.9, "category": "system_event", "tags": {"type": "startup"}} Hope this helps!'
            }
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'backend': 'ollama',
            'confidence_threshold': 0.8
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'System starting up', 'type': 'log'}
        result = await enricher.process(event)
        
        # Should be enriched despite malformed response
        self.assertIn('llm_enrichment', result)
        self.assertEqual(result['llm_enrichment']['confidence'], 0.9)
        self.assertEqual(result['llm_category'], 'system_event')
    
    @patch('httpx.AsyncClient.post')
    async def test_ollama_invalid_json_handling(self, mock_post):
        """Test handling of completely invalid JSON from Ollama."""
        # Mock Ollama response with no valid JSON
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'message': {
                'content': 'This is just plain text with no JSON structure.'
            }
        }
        mock_post.return_value = mock_response
        
        config = {
            'enabled': True,
            'backend': 'ollama'
        }
        enricher = LLMEnricher(config)
        
        event = {'message': 'Test event', 'type': 'log'}
        result = await enricher.process(event)
        
        # Should return original event due to invalid response
        self.assertEqual(result, event)
    
    def test_ollama_backend_configuration(self):
        """Test Ollama backend configuration options."""
        config = {
            'enabled': True,
            'backend': 'ollama',
            'ollama_base_url': 'http://custom-ollama:11434',
            'ollama_model': 'custom-model:latest',
            'ollama_timeout_ms': 45000,
            'ollama_max_tokens': 200
        }
        enricher = LLMEnricher(config)
        
        self.assertEqual(enricher.backend, 'ollama')
        self.assertEqual(enricher.base_url, 'http://custom-ollama:11434')
        self.assertEqual(enricher.model, 'custom-model:latest')
        self.assertEqual(enricher.max_tokens, 200)
        self.assertEqual(enricher.timeout_seconds, 45.0)  # Converted from ms
    
    def test_invalid_backend_rejection(self):
        """Test rejection of invalid backend configuration."""
        config = {
            'enabled': True,
            'backend': 'invalid_backend'
        }
        
        with self.assertRaises(ValueError) as context:
            LLMEnricher(config)
        
        self.assertIn("Invalid LLM backend", str(context.exception))
    
    def test_backend_stats(self):
        """Test backend information in stats."""
        config = {
            'enabled': True,
            'backend': 'ollama'
        }
        enricher = LLMEnricher(config)
        
        stats = enricher.get_stats()
        self.assertEqual(stats['backend'], 'ollama')
        self.assertIn('enabled', stats)
        self.assertIn('confidence_threshold', stats)


if __name__ == '__main__':
    unittest.main()