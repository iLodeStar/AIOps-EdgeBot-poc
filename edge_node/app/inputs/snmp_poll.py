"""SNMP polling input for EdgeBot."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Callable, Optional, Tuple
import structlog
from pysnmp.hlapi.asyncio import *

logger = structlog.get_logger(__name__)

# Common OID to name mappings
OID_MAPPINGS = {
    "1.3.6.1.2.1.1.1.0": "sysDescr",
    "1.3.6.1.2.1.1.2.0": "sysObjectID",
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.2.1.1.4.0": "sysContact",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.2.1.1.6.0": "sysLocation",
    "1.3.6.1.2.1.1.7.0": "sysServices",
    "1.3.6.1.2.1.2.1.0": "ifNumber",
    "1.3.6.1.2.1.2.2.1.1": "ifIndex",
    "1.3.6.1.2.1.2.2.1.2": "ifDescr",
    "1.3.6.1.2.1.2.2.1.3": "ifType",
    "1.3.6.1.2.1.2.2.1.4": "ifMtu",
    "1.3.6.1.2.1.2.2.1.5": "ifSpeed",
    "1.3.6.1.2.1.2.2.1.7": "ifAdminStatus",
    "1.3.6.1.2.1.2.2.1.8": "ifOperStatus",
    "1.3.6.1.2.1.2.2.1.10": "ifInOctets",
    "1.3.6.1.2.1.2.2.1.11": "ifInUcastPkts",
    "1.3.6.1.2.1.2.2.1.13": "ifInDiscards",
    "1.3.6.1.2.1.2.2.1.14": "ifInErrors",
    "1.3.6.1.2.1.2.2.1.16": "ifOutOctets",
    "1.3.6.1.2.1.2.2.1.17": "ifOutUcastPkts",
    "1.3.6.1.2.1.2.2.1.19": "ifOutDiscards",
    "1.3.6.1.2.1.2.2.1.20": "ifOutErrors",
    "1.3.6.1.2.1.25.1.1.0": "hrSystemUptime",
    "1.3.6.1.2.1.25.2.2.0": "hrMemorySize",
    "1.3.6.1.2.1.25.2.3.1.5": "hrStorageSize",
    "1.3.6.1.2.1.25.2.3.1.6": "hrStorageUsed",
    "1.3.6.1.2.1.25.3.2.1.3": "hrProcessorLoad",
}


class SNMPTarget:
    """Represents an SNMP polling target."""

    def __init__(self, config: Dict[str, Any]):
        self.host = config["host"]
        self.community = config.get("community", "public")
        self.port = config.get("port", 161)
        self.interval = config.get("interval", 60)  # seconds
        self.oids = config.get("oids", [])
        self.timeout = config.get("timeout", 5)
        self.retries = config.get("retries", 2)
        self.version = config.get("version", 2)  # SNMPv2c

        # Runtime state
        self.last_poll = 0
        self.consecutive_failures = 0
        self.max_failures = config.get("max_failures", 5)

    def should_poll(self) -> bool:
        """Check if this target should be polled now."""
        return time.time() - self.last_poll >= self.interval

    def is_healthy(self) -> bool:
        """Check if target is considered healthy."""
        return self.consecutive_failures < self.max_failures

    def mark_success(self):
        """Mark polling attempt as successful."""
        self.last_poll = time.time()
        self.consecutive_failures = 0

    def mark_failure(self):
        """Mark polling attempt as failed."""
        self.last_poll = time.time()
        self.consecutive_failures += 1


class SNMPPoller:
    """Async SNMP poller for multiple targets."""

    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.targets = []
        self.running = False
        self.poll_task = None

        # Initialize targets
        for target_config in config.get("targets", []):
            try:
                target = SNMPTarget(target_config)
                self.targets.append(target)
                logger.info(
                    "Added SNMP target",
                    host=target.host,
                    interval=target.interval,
                    oids=len(target.oids),
                )
            except Exception as e:
                logger.error(
                    "Failed to create SNMP target", config=target_config, error=str(e)
                )

    async def start(self):
        """Start the SNMP poller."""
        if not self.config.get("enabled", False):
            logger.info("SNMP input disabled")
            return

        if not self.targets:
            logger.warning("No SNMP targets configured")
            return

        self.running = True
        self.poll_task = asyncio.create_task(self._poll_loop())
        logger.info("SNMP poller started", targets=len(self.targets))

    async def stop(self):
        """Stop the SNMP poller."""
        if not self.running:
            return

        self.running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

        logger.info("SNMP poller stopped")

    async def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                # Check which targets need polling
                poll_tasks = []
                for target in self.targets:
                    if target.should_poll() and target.is_healthy():
                        task = asyncio.create_task(self._poll_target(target))
                        poll_tasks.append(task)

                if poll_tasks:
                    # Wait for all polling tasks to complete
                    await asyncio.gather(*poll_tasks, return_exceptions=True)

                # Sleep for 1 second before next iteration
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("SNMP poll loop cancelled")
                break
            except Exception as e:
                logger.error("Error in SNMP poll loop", error=str(e))
                await asyncio.sleep(5)  # Back off on error

    async def _poll_target(self, target: SNMPTarget):
        """Poll a single SNMP target."""
        try:
            logger.debug("Polling SNMP target", host=target.host)

            # Prepare SNMP request
            if target.version == 1:
                auth_data = CommunityData(target.community, mpModel=0)
            else:
                auth_data = CommunityData(target.community, mpModel=1)

            transport = UdpTransportTarget((target.host, target.port))
            context = ContextData()

            # Poll each OID
            results = []
            for oid in target.oids:
                try:
                    # Perform SNMP GET
                    iterator = getCmd(
                        SnmpEngine(),
                        auth_data,
                        transport,
                        context,
                        ObjectType(ObjectIdentity(oid)),
                    )

                    errorIndication, errorStatus, errorIndex, varBinds = await iterator

                    if errorIndication:
                        logger.warning(
                            "SNMP error indication",
                            host=target.host,
                            oid=oid,
                            error=str(errorIndication),
                        )
                        continue

                    if errorStatus:
                        logger.warning(
                            "SNMP error status",
                            host=target.host,
                            oid=oid,
                            error=f"{errorStatus} at {errorIndex}",
                        )
                        continue

                    # Process successful response
                    for varBind in varBinds:
                        oid_str = str(varBind[0])
                        value = varBind[1]

                        # Convert value to appropriate type
                        if hasattr(value, "prettyPrint"):
                            value_str = value.prettyPrint()
                        else:
                            value_str = str(value)

                        # Try to convert to numeric if possible
                        try:
                            if "." not in value_str and value_str.isdigit():
                                numeric_value = int(value_str)
                            else:
                                numeric_value = float(value_str)
                        except (ValueError, TypeError):
                            numeric_value = None

                        result = {
                            "oid": oid_str,
                            "oid_name": OID_MAPPINGS.get(oid_str, f"unknown_{oid_str}"),
                            "value": value_str,
                            "numeric_value": numeric_value,
                            "type": str(type(value).__name__),
                        }
                        results.append(result)

                except Exception as e:
                    logger.warning(
                        "Error polling OID", host=target.host, oid=oid, error=str(e)
                    )

            if results:
                # Create message for results
                message = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "snmp",
                    "host": target.host,
                    "port": target.port,
                    "community": target.community,
                    "version": f"v{target.version}",
                    "poll_interval": target.interval,
                    "oids_count": len(results),
                    "results": results,
                }

                await self.message_callback(message)
                target.mark_success()

                logger.debug(
                    "SNMP poll successful", host=target.host, oids_polled=len(results)
                )
            else:
                target.mark_failure()
                logger.warning("No SNMP results obtained", host=target.host)

        except asyncio.CancelledError:
            logger.debug("SNMP polling cancelled", host=target.host)
            raise
        except Exception as e:
            target.mark_failure()
            logger.error("Error polling SNMP target", host=target.host, error=str(e))

            # Still create an error message
            error_message = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "snmp_error",
                "host": target.host,
                "port": target.port,
                "error": str(e),
                "consecutive_failures": target.consecutive_failures,
            }

            try:
                await self.message_callback(error_message)
            except Exception as callback_error:
                logger.error(
                    "Error sending SNMP error message", error=str(callback_error)
                )

    def get_status(self) -> Dict[str, Any]:
        """Get status information about the SNMP poller."""
        return {
            "enabled": self.config.get("enabled", False),
            "running": self.running,
            "targets": len(self.targets),
            "healthy_targets": len([t for t in self.targets if t.is_healthy()]),
            "target_status": [
                {
                    "host": target.host,
                    "healthy": target.is_healthy(),
                    "consecutive_failures": target.consecutive_failures,
                    "last_poll": target.last_poll,
                    "next_poll": target.last_poll + target.interval,
                }
                for target in self.targets
            ],
        }


# Factory function for creating SNMP poller
def create_snmp_poller(
    config: Dict[str, Any], message_callback: Callable
) -> SNMPPoller:
    """Create an SNMP poller instance."""
    return SNMPPoller(config, message_callback)
