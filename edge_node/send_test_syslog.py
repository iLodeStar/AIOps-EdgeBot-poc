#!/usr/bin/env python3
"""Test script to send syslog messages to EdgeBot."""
import socket
import time


def send_test_syslog_messages():
    """Send test syslog messages via UDP and TCP."""

    # Test RFC3164 message
    rfc3164_msg = (
        "<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8"
    )

    # Test RFC5424 message
    rfc5424_msg = "<165>1 2003-08-24T05:14:15.000003-07:00 192.0.2.1 myproc 8710 - - %% It's time to make the do-nuts."

    print("Sending test syslog messages...")

    # Send UDP messages
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print("Sending RFC3164 message via UDP...")
        sock.sendto(rfc3164_msg.encode("utf-8"), ("localhost", 5514))
        time.sleep(0.1)

        print("Sending RFC5424 message via UDP...")
        sock.sendto(rfc5424_msg.encode("utf-8"), ("localhost", 5514))

        sock.close()
        print("✅ UDP messages sent successfully")

    except Exception as e:
        print(f"❌ Failed to send UDP messages: {e}")

    # Send TCP messages
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("localhost", 5515))

        print("Sending RFC3164 message via TCP...")
        sock.send((rfc3164_msg + "\n").encode("utf-8"))
        time.sleep(0.1)

        print("Sending RFC5424 message via TCP...")
        sock.send((rfc5424_msg + "\n").encode("utf-8"))

        sock.close()
        print("✅ TCP messages sent successfully")

    except Exception as e:
        print(f"❌ Failed to send TCP messages: {e}")


if __name__ == "__main__":
    send_test_syslog_messages()
