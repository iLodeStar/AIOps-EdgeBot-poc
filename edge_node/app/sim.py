import random
import time
from datetime import datetime, timezone
from typing import Dict, Union


class TelemetrySimulator:
    """Simulates telemetry data for edge nodes"""
    
    def __init__(self, edge_id: str):
        self.edge_id = edge_id
        self.base_values = {
            'cpu_percent': 45.0,
            'memory_percent': 60.0,
            'temperature': 35.0,
            'network_latency_ms': 10.0
        }
        self.trends = {
            'cpu_percent': 0.0,
            'memory_percent': 0.0,
            'temperature': 0.0,
            'network_latency_ms': 0.0
        }
        
    def generate_telemetry(self) -> Dict[str, Union[float, str, int]]:
        """Generate simulated telemetry data"""
        # Create some time-based variation
        now = datetime.now(timezone.utc)
        time_factor = now.timestamp() / 3600  # Hour-based cycles
        
        metrics = {}
        
        for metric, base_value in self.base_values.items():
            # Add some random noise
            noise = random.uniform(-5, 5)
            
            # Add occasional spikes for anomaly detection testing
            spike_chance = 0.05  # 5% chance of spike
            if random.random() < spike_chance:
                if metric == 'cpu_percent':
                    spike = random.uniform(30, 40)  # CPU spike
                elif metric == 'temperature':
                    spike = random.uniform(20, 30)  # Temperature spike
                elif metric == 'network_latency_ms':
                    spike = random.uniform(50, 100)  # Latency spike
                else:
                    spike = random.uniform(20, 30)  # General spike
                noise += spike
                
            # Apply trend (gradual drift)
            trend = self.trends.get(metric, 0.0)
            
            # Calculate final value
            value = base_value + noise + trend
            
            # Apply realistic bounds
            if metric == 'cpu_percent':
                value = max(0, min(100, value))
            elif metric == 'memory_percent':
                value = max(0, min(100, value))
            elif metric == 'temperature':
                value = max(0, min(100, value))
            elif metric == 'network_latency_ms':
                value = max(0, value)
            
            metrics[metric] = round(value, 2)
        
        # Add some categorical metrics
        metrics['status'] = random.choice(['healthy', 'warning', 'critical'])
        metrics['node_type'] = 'edge'
        metrics['uptime_hours'] = int((time.time() % 86400) / 3600)
        
        # Update trends occasionally
        if random.random() < 0.1:  # 10% chance to update trend
            for metric in self.trends:
                self.trends[metric] += random.uniform(-0.5, 0.5)
                # Keep trends bounded
                self.trends[metric] = max(-10, min(10, self.trends[metric]))
        
        return metrics
    
    def get_current_timestamp(self) -> str:
        """Get current timestamp in RFC3339 format"""
        return datetime.now(timezone.utc).isoformat()


def create_telemetry_data(edge_id: str) -> Dict:
    """Create a complete telemetry data payload"""
    simulator = TelemetrySimulator(edge_id)
    return {
        'edge_id': edge_id,
        'ts': simulator.get_current_timestamp(),
        'metrics': simulator.generate_telemetry()
    }