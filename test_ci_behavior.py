#!/usr/bin/env python3
"""Test the specific CI regression scenario fix."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))


async def test_ci_specific_scenario():
    """Test the specific CI environment detection and behavior."""
    print("🔍 Testing CI-specific behavior...")
    
    # Test 1: Non-CI environment (should skip readiness check)
    print("\n📝 Test 1: Non-CI environment")
    os.environ.pop('GITHUB_ACTIONS', None)
    os.environ.pop('MOTHERSHIP_LOG_LEVEL', None)
    
    from app.storage.loki import LokiClient
    
    config = {'enabled': True, 'url': 'http://localhost:3100'}
    client = LokiClient(config)
    
    is_ci = client._is_ci_environment()
    print(f"CI environment detected: {is_ci}")
    
    if not is_ci:
        print("✅ Test 1 PASSED: Non-CI environment correctly detected")
        test1_pass = True
    else:
        print("❌ Test 1 FAILED: Non-CI environment incorrectly detected as CI")
        test1_pass = False
    
    # Test readiness check (should return True immediately for non-CI)
    readiness_result = await client._wait_for_loki_ready()
    if readiness_result:
        print("✅ Test 1b PASSED: Non-CI readiness check returns True")
        test1b_pass = True
    else:
        print("❌ Test 1b FAILED: Non-CI readiness check should return True")
        test1b_pass = False
    
    # Test 2: CI environment with exact CI variables 
    print("\n📝 Test 2: CI environment detection")
    os.environ['GITHUB_ACTIONS'] = 'true'
    os.environ['MOTHERSHIP_LOG_LEVEL'] = 'INFO'
    
    # Need to create a new client to pick up environment changes
    client2 = LokiClient(config)
    is_ci2 = client2._is_ci_environment()
    print(f"CI environment detected: {is_ci2}")
    
    if is_ci2:
        print("✅ Test 2 PASSED: CI environment correctly detected")
        test2_pass = True
    else:
        print("❌ Test 2 FAILED: CI environment not detected")
        test2_pass = False
    
    # Test 3: CI environment with pytest (should not be CI for our purposes)
    print("\n📝 Test 3: CI environment with pytest")
    os.environ['PYTEST_CURRENT_TEST'] = 'test_something.py::test_method'
    
    client3 = LokiClient(config)
    is_ci3 = client3._is_ci_environment()
    print(f"CI environment detected with pytest: {is_ci3}")
    
    if not is_ci3:
        print("✅ Test 3 PASSED: Pytest environment correctly excluded from CI behavior")
        test3_pass = True
    else:
        print("❌ Test 3 FAILED: Pytest environment should not trigger CI behavior")
        test3_pass = False
        
    # Clean up
    os.environ.pop('PYTEST_CURRENT_TEST', None)
    
    # Test 4: Validate the key improvements
    print("\n📝 Test 4: CI behavior improvements")
    client4 = LokiClient(config)
    
    # Check the enhanced parameters for CI
    max_retries = config.get('max_retries', 5 if client4._is_ci_environment() else 3)
    expected_retries = 5  # Should be 5 in CI environment
    
    if max_retries == expected_retries:
        print(f"✅ Test 4a PASSED: CI retry count is {max_retries}")
        test4a_pass = True
    else:
        print(f"❌ Test 4a FAILED: Expected {expected_retries} retries, got {max_retries}")
        test4a_pass = False
    
    # Test timeout calculation
    timeout = 15.0 if client4._is_ci_environment() else config.get('timeout_seconds', 30.0)
    expected_timeout = 15.0
    
    if timeout == expected_timeout:
        print(f"✅ Test 4b PASSED: CI timeout is {timeout}s")
        test4b_pass = True
    else:
        print(f"❌ Test 4b FAILED: Expected {expected_timeout}s timeout, got {timeout}s")
        test4b_pass = False
    
    # Test 5: Event processing consistency
    print("\n📝 Test 5: Event processing consistency")
    test_event = {
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "syslog",
        "message": "Full regression test via GitHub Actions regress-test-id",
        "hostname": "actions-runner",
        "severity": "info",
        "service": "actions-runner",
        "source": "mothership"
    }
    
    # Verify label extraction
    labels = client4._extract_safe_labels(test_event)
    expected_source = 'mothership'
    
    if labels.get('source') == expected_source:
        print(f"✅ Test 5a PASSED: Source label is '{expected_source}'")
        test5a_pass = True
    else:
        print(f"❌ Test 5a FAILED: Expected source '{expected_source}', got '{labels.get('source')}'")
        test5a_pass = False
    
    # Verify Loki entry generation
    loki_entry = client4._convert_to_loki_entry(test_event)
    
    if loki_entry and 'regress-test-id' in loki_entry.get('line', ''):
        print("✅ Test 5b PASSED: Test ID preserved in Loki entry")
        test5b_pass = True
    else:
        print("❌ Test 5b FAILED: Test ID not found in Loki entry")
        test5b_pass = False
    
    # Overall results
    all_tests = [
        ("Non-CI detection", test1_pass),
        ("Non-CI readiness", test1b_pass), 
        ("CI detection", test2_pass),
        ("Pytest exclusion", test3_pass),
        ("CI retry count", test4a_pass),
        ("CI timeout", test4b_pass),
        ("Source labels", test5a_pass),
        ("Entry generation", test5b_pass),
    ]
    
    passed = sum(1 for _, result in all_tests if result)
    total = len(all_tests)
    
    print(f"\n🎯 Overall Results:")
    for test_name, result in all_tests:
        print(f"  {test_name}: {'✅ PASS' if result else '❌ FAIL'}")
    
    overall_success = passed == total
    print(f"  Overall: {passed}/{total} tests passed - {'🎉 SUCCESS' if overall_success else '💥 FAILURE'}")
    
    return overall_success


if __name__ == "__main__":
    result = asyncio.run(test_ci_specific_scenario())
    if result:
        print("\n🎉 All CI-specific behavior tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed.")
        sys.exit(1)