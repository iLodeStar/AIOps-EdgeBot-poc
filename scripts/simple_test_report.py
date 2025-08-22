#!/usr/bin/env python3
"""
Create a simple, non-technical test summary from a JUnit XML, and print to stdout.
Also suitable for saving to reports/simple_report.md in CI.
"""
import sys
import xml.etree.ElementTree as ET

def main(path: str):
    tree = ET.parse(path)
    root = tree.getroot()
    
    # Find the testsuite element (pytest uses testsuites -> testsuite)
    testsuite = root.find(".//testsuite")
    if testsuite is None:
        # fallback to root if it's already a testsuite
        testsuite = root
    
    total = int(testsuite.attrib.get("tests", 0))
    failures = int(testsuite.attrib.get("failures", 0)) + int(testsuite.attrib.get("errors", 0))
    skipped = int(testsuite.attrib.get("skipped", 0))
    passed = total - failures - skipped

    print("# EdgeBot Test Summary\n")
    print(f"- Total scenarios: {total}")
    print(f"- Passed: {passed}")
    print(f"- Failed: {failures}")
    print(f"- Skipped: {skipped}\n")

    print("## Scenarios")
    for case in root.iter("testcase"):
        name = case.attrib.get("name")
        classname = case.attrib.get("classname", "")
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped_node = case.find("skipped")
        status = "PASSED"
        if failed:
            status = "FAILED"
        elif skipped_node is not None:
            status = "SKIPPED"
        print(f"- {name} ({classname}): {status}")

    print("\n---\nTechnical logs are attached in 'test-output.txt' and 'reports/report.html' for engineers.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: simple_test_report.py path/to/junit.xml", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])