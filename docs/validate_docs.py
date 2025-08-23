#!/usr/bin/env python3
"""
Documentation Validation Tool for AIOps EdgeBot

This tool validates:
1. Markdown files for broken relative links to files in the repo
2. Referenced paths exist (images, scripts, code snippets)
3. Optional: External link HEAD check with timeout

Usage:
    python docs/validate_docs.py --check-links --check-references [--check-external]
"""
import argparse
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple, Optional
from urllib.parse import urlparse
import requests


class DocumentationValidator:
    """Validates documentation files for broken links and references."""
    
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def find_markdown_files(self) -> List[Path]:
        """Find all Markdown files in the repository."""
        markdown_files = []
        
        # Search in repository root and docs/ directory
        for pattern in ["*.md", "docs/**/*.md", "**/README.md"]:
            markdown_files.extend(self.root_dir.glob(pattern))
            
        # Remove duplicates and sort
        return sorted(list(set(markdown_files)))
        
    def extract_links(self, file_path: Path) -> List[Tuple[str, int]]:
        """Extract all links from a Markdown file."""
        links = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Regular expressions for different link formats
            link_patterns = [
                # [text](link)
                r'\[([^\]]+)\]\(([^)]+)\)',
                # ![alt](image)  
                r'!\[([^\]]*)\]\(([^)]+)\)',
                # <link>
                r'<(https?://[^>]+)>',
                # Raw URLs
                r'(?:^|\s)(https?://[^\s]+)'
            ]
            
            for line_num, line in enumerate(content.split('\n'), 1):
                for pattern in link_patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        if len(match.groups()) >= 2:
                            link = match.group(2)
                        else:
                            link = match.group(1)
                        links.append((link.strip(), line_num))
                        
        except Exception as e:
            self.warnings.append(f"Failed to read {file_path}: {e}")
            
        return links
        
    def validate_relative_link(self, link: str, source_file: Path) -> bool:
        """Validate a relative link exists in the repository."""
        # Skip external links, anchors, and mailto links
        if (link.startswith(('http://', 'https://', 'ftp://')) or 
            link.startswith('#') or 
            link.startswith('mailto:')):
            return True
            
        # Clean up the link (remove anchors and query parameters)
        clean_link = link.split('#')[0].split('?')[0]
        if not clean_link:  # Just an anchor
            return True
            
        # Resolve relative path from source file
        source_dir = source_file.parent
        target_path = (source_dir / clean_link).resolve()
        
        # Check if target is within repository
        try:
            target_path.relative_to(self.root_dir)
        except ValueError:
            # Path is outside repository - could be valid
            return True
            
        # Check if target exists
        if not target_path.exists():
            # Try common variations
            variations = [
                target_path,
                target_path.with_suffix('.md'),
                target_path / 'README.md',
                target_path / 'index.md'
            ]
            
            for variation in variations:
                if variation.exists():
                    return True
                    
            return False
            
        return True
        
    def check_external_link(self, link: str, timeout: int = 5) -> bool:
        """Check if external link is accessible."""
        try:
            response = requests.head(link, timeout=timeout, allow_redirects=True)
            return response.status_code < 400
        except requests.RequestException:
            # Try GET request if HEAD fails
            try:
                response = requests.get(link, timeout=timeout, stream=True)
                return response.status_code < 400
            except requests.RequestException:
                return False
                
    def validate_code_references(self, file_path: Path) -> List[str]:
        """Find and validate code file references in documentation."""
        errors = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Look for code block references and file paths
            patterns = [
                # File: `path/to/file.py`
                r'File:\s*`([^`]+)`',
                # ```lang path/to/file
                r'```\w*\s+([^\s\n]+\.(py|js|yaml|yml|json|sh|md))',
                # Common file path patterns
                r'`([^`]*\.(py|js|yaml|yml|json|sh|md|txt|conf))`',
            ]
            
            for line_num, line in enumerate(content.split('\n'), 1):
                for pattern in patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        file_ref = match.group(1).strip()
                        
                        # Skip URLs and absolute paths outside repo
                        if (file_ref.startswith(('http://', 'https://', '/usr/', '/opt/')) or
                            file_ref in ['config.yaml', 'requirements.txt']):  # Common generic names
                            continue
                            
                        # Check if referenced file exists
                        ref_path = self.root_dir / file_ref
                        if not ref_path.exists():
                            # Try relative to current doc file
                            alt_path = file_path.parent / file_ref
                            if not alt_path.exists():
                                errors.append(
                                    f"{file_path.relative_to(self.root_dir)}:{line_num}: "
                                    f"Referenced file not found: {file_ref}"
                                )
                                
        except Exception as e:
            self.warnings.append(f"Failed to validate code references in {file_path}: {e}")
            
        return errors
        
    def validate_image_references(self, file_path: Path) -> List[str]:
        """Find and validate image references in documentation."""
        errors = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Find image references
            image_pattern = r'!\[[^\]]*\]\(([^)]+)\)'
            
            for line_num, line in enumerate(content.split('\n'), 1):
                matches = re.finditer(image_pattern, line)
                for match in matches:
                    img_src = match.group(1).strip()
                    
                    # Skip external images
                    if img_src.startswith(('http://', 'https://')):
                        continue
                        
                    # Check if image file exists
                    img_path = file_path.parent / img_src
                    if not img_path.exists():
                        # Try from repository root
                        alt_path = self.root_dir / img_src
                        if not alt_path.exists():
                            errors.append(
                                f"{file_path.relative_to(self.root_dir)}:{line_num}: "
                                f"Image not found: {img_src}"
                            )
                            
        except Exception as e:
            self.warnings.append(f"Failed to validate image references in {file_path}: {e}")
            
        return errors
        
    def validate_links_in_file(self, file_path: Path, check_external: bool = False) -> None:
        """Validate all links in a single file."""
        relative_path = file_path.relative_to(self.root_dir)
        print(f"  Checking: {relative_path}")
        
        links = self.extract_links(file_path)
        
        for link, line_num in links:
            if link.startswith(('http://', 'https://')):
                if check_external:
                    if not self.check_external_link(link):
                        self.errors.append(
                            f"{relative_path}:{line_num}: External link not accessible: {link}"
                        )
            else:
                if not self.validate_relative_link(link, file_path):
                    self.errors.append(
                        f"{relative_path}:{line_num}: Broken relative link: {link}"
                    )
                    
    def validate_all_links(self, check_external: bool = False) -> bool:
        """Validate links in all Markdown files."""
        print("🔗 Validating documentation links...")
        
        markdown_files = self.find_markdown_files()
        print(f"Found {len(markdown_files)} Markdown files")
        
        for file_path in markdown_files:
            self.validate_links_in_file(file_path, check_external)
            
        return len(self.errors) == 0
        
    def validate_all_references(self) -> bool:
        """Validate code and image references in all Markdown files."""
        print("📋 Validating file references...")
        
        markdown_files = self.find_markdown_files()
        
        for file_path in markdown_files:
            relative_path = file_path.relative_to(self.root_dir)
            print(f"  Checking references: {relative_path}")
            
            # Check code file references
            code_errors = self.validate_code_references(file_path)
            self.errors.extend(code_errors)
            
            # Check image references  
            image_errors = self.validate_image_references(file_path)
            self.errors.extend(image_errors)
            
        return len(self.errors) == 0
        
    def print_results(self) -> None:
        """Print validation results."""
        print("\n" + "="*60)
        
        if self.warnings:
            print("⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"  - {warning}")
            print()
            
        if self.errors:
            print("❌ ERRORS FOUND:")
            for error in self.errors:
                print(f"  - {error}")
            print(f"\nTotal errors: {len(self.errors)}")
        else:
            print("✅ All documentation validation checks passed!")
            
        print("="*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Validate AIOps EdgeBot documentation')
    parser.add_argument('--check-links', action='store_true',
                       help='Check for broken relative links')
    parser.add_argument('--check-references', action='store_true', 
                       help='Check for missing referenced files')
    parser.add_argument('--check-external', action='store_true',
                       help='Check external links (slow)')
    parser.add_argument('--root-dir', type=str, default='.',
                       help='Repository root directory')
    
    args = parser.parse_args()
    
    if not (args.check_links or args.check_references):
        parser.error('Must specify at least one of --check-links or --check-references')
        
    # Initialize validator
    root_dir = Path(args.root_dir).resolve()
    if not root_dir.exists():
        print(f"❌ Root directory not found: {root_dir}")
        sys.exit(1)
        
    validator = DocumentationValidator(root_dir)
    
    print(f"📚 AIOps EdgeBot Documentation Validator")
    print(f"Repository: {root_dir}")
    print()
    
    # Run validations
    all_passed = True
    
    if args.check_links:
        passed = validator.validate_all_links(check_external=args.check_external)
        all_passed = all_passed and passed
        
    if args.check_references:
        passed = validator.validate_all_references()
        all_passed = all_passed and passed
        
    # Print results
    validator.print_results()
    
    # Exit with appropriate code
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()