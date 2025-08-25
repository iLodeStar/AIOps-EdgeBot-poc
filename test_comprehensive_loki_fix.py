#!/usr/bin/env python3
"""
Comprehensive test of the Loki fix for CI regression tests.
Tests all scenarios: working Loki, unavailable Loki, and startup delay.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set the EXACT environment variables used in CI regression test
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"  
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"

# CI environment flags
os.environ["GITHUB_ACTIONS"] = "true"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_comprehensive_loki_fix():
    """Comprehensive test of all Loki scenarios."""
    
    print("🧪 Comprehensive Loki Fix Validation")
    print("=" * 50)
    
    results = {}
    
    # Test 1: Working Loki (should succeed)
    print("\n🔍 Test 1: Working Loki scenario")
    try:
        from test_ci_loki_reproduction import test_ci_loki_reproduction
        result = await test_ci_loki_reproduction()
        results["working_loki"] = result
        print("✅ Working Loki test:", "PASSED" if result else "FAILED")
    except Exception as e:
        print(f"❌ Working Loki test failed: {e}")
        results["working_loki"] = False
    
    await asyncio.sleep(1)  # Brief pause between tests
    
    # Test 2: Unavailable Loki (should handle gracefully)
    print("\n🔍 Test 2: Unavailable Loki scenario") 
    try:
        from test_loki_unavailable import test_loki_unavailable_scenario
        result = await test_loki_unavailable_scenario()
        results["unavailable_loki"] = result
        print("✅ Unavailable Loki test:", "PASSED" if result else "FAILED")
    except Exception as e:
        print(f"❌ Unavailable Loki test failed: {e}")
        results["unavailable_loki"] = False
    
    await asyncio.sleep(1)  # Brief pause between tests
    
    # Test 3: Startup delay Loki (should succeed with fix)
    print("\n🔍 Test 3: Loki startup delay scenario")
    try:
        from test_loki_startup_delay import test_loki_startup_delay_scenario
        result = await test_loki_startup_delay_scenario()
        results["startup_delay_loki"] = result
        print("✅ Startup delay Loki test:", "PASSED" if result else "FAILED")
    except Exception as e:
        print(f"❌ Startup delay Loki test failed: {e}")
        results["startup_delay_loki"] = False
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name.replace('_', ' ').title()}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 ALL TESTS PASSED - Loki fix is working correctly!")
        print("\nThe fix should resolve the CI regression test failures by:")
        print("- ✅ Properly handling Loki startup delays")
        print("- ✅ Ensuring events are written when Loki is available")
        print("- ✅ Gracefully handling Loki unavailability")
        print("- ✅ Working correctly in CI environments")
    else:
        print("❌ SOME TESTS FAILED - Further investigation needed")
        
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(test_comprehensive_loki_fix())
    if success:
        print("\n🚀 Ready to deploy the Loki fix!")
        sys.exit(0)
    else:
        print("\n⚠️  Fix needs more work")
        sys.exit(1)