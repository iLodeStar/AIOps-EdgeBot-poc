"""Deterministic enrichment processors."""
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union
from urllib.parse import urlparse
import structlog
from .processor import Processor

logger = structlog.get_logger()

class AddTagsProcessor(Processor):
    """Processor that adds static tags to events."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "AddTags")
        self.add_tags = config.get('add_tags', {})
        logger.info(f"Initialized AddTags processor", tags=self.add_tags)
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Add configured tags to the event."""
        processed_event = event.copy()
        
        # Add tags, preserving existing ones
        if 'tags' not in processed_event:
            processed_event['tags'] = {}
        
        for key, value in self.add_tags.items():
            processed_event['tags'][key] = value
        
        return processed_event


class SeverityMapProcessor(Processor):
    """Processor that maps string severities to numeric values."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "SeverityMap")
        self.severity_mapping = config.get('severity_mapping', {
            'emergency': 0, 'emerg': 0,
            'alert': 1,
            'critical': 2, 'crit': 2,
            'error': 3, 'err': 3, 'fatal': 3,
            'warning': 4, 'warn': 4,
            'notice': 5,
            'informational': 6, 'info': 6,
            'debug': 7
        })
        logger.info(f"Initialized SeverityMap processor", 
                   mappings=len(self.severity_mapping))
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Map severity strings to numeric values."""
        processed_event = event.copy()
        
        if 'severity' in processed_event:
            severity = str(processed_event['severity']).lower().strip()
            
            if severity in self.severity_mapping:
                processed_event['severity_num'] = self.severity_mapping[severity]
                logger.debug("Mapped severity", 
                           original=processed_event['severity'],
                           numeric=processed_event['severity_num'])
            elif severity.isdigit():
                # Already numeric, just copy
                processed_event['severity_num'] = int(severity)
        
        return processed_event


class ServiceFromPathProcessor(Processor):
    """Processor that extracts service names from log paths or hostnames."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "ServiceFromPath")
        
        # Path-to-service mapping patterns
        self.path_patterns = config.get('path_patterns', [
            (r'/var/log/nginx/', 'nginx'),
            (r'/var/log/apache/', 'apache'),
            (r'/var/log/mysql/', 'mysql'),
            (r'/var/log/postgresql/', 'postgresql'),
            (r'/var/log/redis/', 'redis'),
            (r'/var/log/docker/', 'docker'),
            (r'/var/log/kubernetes/', 'kubernetes'),
            (r'/opt/([^/]+)/', r'\1'),  # Extract service from /opt/servicename/
        ])
        
        # Compile regex patterns
        self.compiled_patterns = []
        for pattern, service in self.path_patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self.compiled_patterns.append((compiled, service))
            except re.error as e:
                logger.warning(f"Invalid service pattern: {pattern}", error=str(e))
        
        logger.info(f"Initialized ServiceFromPath processor", 
                   patterns=len(self.compiled_patterns))
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract service name from paths or hostnames."""
        processed_event = event.copy()
        service_name = None
        
        # Try to extract from various fields
        path_fields = ['path', 'file', 'source', 'log_file', 'filename']
        for field in path_fields:
            if field in processed_event and processed_event[field]:
                service_name = self._extract_service_from_path(str(processed_event[field]))
                if service_name:
                    break
        
        # Try hostname if no service found
        if not service_name:
            hostname_fields = ['hostname', 'host', 'source_host']
            for field in hostname_fields:
                if field in processed_event and processed_event[field]:
                    service_name = self._extract_service_from_hostname(str(processed_event[field]))
                    if service_name:
                        break
        
        if service_name:
            processed_event['service'] = service_name
            logger.debug("Extracted service", service=service_name)
        
        return processed_event
    
    def _extract_service_from_path(self, path: str) -> Optional[str]:
        """Extract service name from file path."""
        for pattern, service_template in self.compiled_patterns:
            match = pattern.search(path)
            if match:
                if '\\' in service_template:  # Regex substitution
                    # Use the match directly for group substitution
                    return match.expand(service_template)
                else:
                    return service_template
        return None
    
    def _extract_service_from_hostname(self, hostname: str) -> Optional[str]:
        """Extract service name from hostname."""
        # Simple heuristic: first part of FQDN
        parts = hostname.split('.')
        if len(parts) > 1:
            return parts[0]
        return hostname


class GeoHintProcessor(Processor):
    """Processor that adds geographical hints based on source IP."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "GeoHint")
        
        # Static IP to location mapping (for known infrastructure)
        self.ip_location_map = config.get('ip_location_map', {})
        
        # Subnet to location mapping
        self.subnet_location_map = config.get('subnet_location_map', {})
        
        logger.info(f"Initialized GeoHint processor", 
                   ip_mappings=len(self.ip_location_map),
                   subnet_mappings=len(self.subnet_location_map))
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Add geographical hints to the event."""
        processed_event = event.copy()
        
        # Try to get IP address from various fields
        ip_fields = ['source_ip', 'client_ip', 'remote_addr', 'ip', 'src_ip']
        source_ip = None
        
        for field in ip_fields:
            if field in processed_event and processed_event[field]:
                source_ip = str(processed_event[field])
                break
        
        if source_ip:
            location = self._get_location_hint(source_ip)
            if location:
                processed_event['geo_hint'] = location
                logger.debug("Added geo hint", ip=source_ip, location=location)
        
        return processed_event
    
    def _get_location_hint(self, ip: str) -> Optional[Dict[str, Any]]:
        """Get location hint for IP address."""
        # Direct IP lookup
        if ip in self.ip_location_map:
            return self.ip_location_map[ip]
        
        # Subnet lookup
        for subnet, location in self.subnet_location_map.items():
            if self._ip_in_subnet(ip, subnet):
                return location
        
        return None
    
    def _ip_in_subnet(self, ip: str, subnet: str) -> bool:
        """Simple subnet check (basic implementation)."""
        try:
            # This is a simplified implementation
            # In production, use ipaddress module
            if '/' not in subnet:
                return ip == subnet
            
            network, prefix_len = subnet.split('/')
            prefix_len = int(prefix_len)
            
            # Convert IPs to integers for comparison
            ip_int = self._ip_to_int(ip)
            network_int = self._ip_to_int(network)
            
            # Create subnet mask
            mask = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
            
            return (ip_int & mask) == (network_int & mask)
        except:
            return False
    
    def _ip_to_int(self, ip: str) -> int:
        """Convert IP string to integer."""
        parts = ip.split('.')
        return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])


class SiteEnvTagsProcessor(Processor):
    """Processor that adds site and environment tags based on hostname patterns."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "SiteEnvTags")
        
        # Hostname patterns to extract site/env
        self.site_patterns = config.get('site_patterns', [
            (r'\.([a-z]{2,3})\.(prod|production)\.', {'env': 'production', 'site': r'\1'}),
            (r'\.([a-z]{2,3})\.(dev|development)\.', {'env': 'development', 'site': r'\1'}),
            (r'\.([a-z]{2,3})\.(test|testing)\.', {'env': 'test', 'site': r'\1'}),
            (r'\.([a-z]{2,3})\.(stage|staging)\.', {'env': 'staging', 'site': r'\1'}),
        ])
        
        # Default values
        self.default_site = config.get('default_site')
        self.default_env = config.get('default_env')
        
        # Compile patterns
        self.compiled_patterns = []
        for pattern, tags in self.site_patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self.compiled_patterns.append((compiled, tags))
            except re.error as e:
                logger.warning(f"Invalid site pattern: {pattern}", error=str(e))
        
        logger.info(f"Initialized SiteEnvTags processor", 
                   patterns=len(self.compiled_patterns))
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Add site and environment tags based on hostname."""
        processed_event = event.copy()
        
        # Get hostname
        hostname_fields = ['hostname', 'host', 'source_host']
        hostname = None
        
        for field in hostname_fields:
            if field in processed_event and processed_event[field]:
                hostname = str(processed_event[field])
                break
        
        if hostname:
            site, env = self._extract_site_env(hostname)
            
            if site or env:
                if 'tags' not in processed_event:
                    processed_event['tags'] = {}
                
                if site:
                    processed_event['tags']['site'] = site
                if env:
                    processed_event['tags']['environment'] = env
                
                logger.debug("Added site/env tags", 
                           hostname=hostname, site=site, env=env)
        
        # Add defaults if not set
        if self.default_site and 'tags' in processed_event and 'site' not in processed_event['tags']:
            processed_event['tags']['site'] = self.default_site
        
        if self.default_env and 'tags' in processed_event and 'environment' not in processed_event['tags']:
            processed_event['tags']['environment'] = self.default_env
        
        return processed_event
    
    def _extract_site_env(self, hostname: str) -> tuple:
        """Extract site and environment from hostname."""
        for pattern, tags in self.compiled_patterns:
            match = pattern.search(hostname)
            if match:
                site = None
                env = None
                
                if 'site' in tags:
                    site_template = tags['site']
                    if '\\' in site_template:  # Regex substitution
                        site = match.expand(site_template)
                    else:
                        site = site_template
                
                if 'env' in tags:
                    env_template = tags['env']
                    if '\\' in env_template:  # Regex substitution
                        env = match.expand(env_template)
                    else:
                        env = env_template
                
                return site, env
        
        return None, None


class TimestampNormalizer(Processor):
    """Processor that normalizes timestamps to ISO format."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "TimestampNormalizer")
        self.timestamp_fields = config.get('timestamp_fields', ['timestamp', 'time', '@timestamp'])
        self.default_timezone = config.get('default_timezone', 'UTC')
        
        logger.info(f"Initialized TimestampNormalizer processor",
                   fields=self.timestamp_fields)
    
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize timestamp to ISO format."""
        processed_event = event.copy()
        
        for field in self.timestamp_fields:
            if field in processed_event:
                normalized_ts = self._normalize_timestamp(processed_event[field])
                if normalized_ts:
                    processed_event[field] = normalized_ts
                    break
        
        # Ensure there's always a timestamp
        if not any(field in processed_event for field in self.timestamp_fields):
            processed_event['timestamp'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        return processed_event
    
    def _normalize_timestamp(self, ts: Any) -> Optional[str]:
        """Normalize various timestamp formats to ISO string."""
        try:
            if isinstance(ts, str):
                # Try parsing various formats
                for fmt in ['%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', 
                           '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S']:
                    try:
                        dt = datetime.strptime(ts, fmt)
                        return dt.replace(tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                    except ValueError:
                        continue
                
                # If already ISO format, return as-is
                if 'T' in ts and ('Z' in ts or '+' in ts or '-' in ts[-6:]):
                    return ts
            
            elif isinstance(ts, (int, float)):
                # Unix timestamp
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            return None
        except:
            return None