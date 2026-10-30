#!/usr/bin/env python3
"""
NexusStream Pro — Command Line Interface for Core Functionality Testing
This version tests the core download and processing features without GUI.
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

# Add main.py directory to path for module import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import DownloadEngine, SettingsManager, HistoryManager

def test_url_parsing():
    """Test URL inspection functionality"""
    print("=== URL Inspection Test ===")
    test_urls = [
        "https://www.youtube.com/watch?v=BaW_jenozKc",  # Big Buck Bunny (test)
        "https://www.youtube.com/playlist?list=PL4lCao7KL_Qq_8lRZ1j5X5uX0eJQ5Xc8U"  # Sample playlist
    ]
    
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        info = DownloadEngine.fetch_metadata(url)
        if info and 'error' not in info:
            print(f"  - Type: {info.get('type', 'unknown')}")
            if info.get('type') == 'video':
                print(f"  - Title: {info.get('title')}")
                print(f"  - Duration: {info.get('duration')}s")
                print(f"  - Formats: {len(info.get('formats', []))}")
            elif info.get('type') == 'playlist':
                print(f"  - Playlist Title: {info.get('title')}")
                print(f"  - Item Count: {info.get('count')}")
        else:
            print(f"  - Error: {info.get('error', 'Unknown error')}")

def test_history():
    """Test history save/load functionality"""
    print("\n=== History Test ===")
    
    # Add test entry
    test_entry = {
        'title': 'Test Download',
        'url': 'https://example.com/test',
        'time': time.strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'Success'
    }
    
    HistoryManager.add(test_entry)
    print("Added test entry to history")
    
    # Load history
    history = HistoryManager.load()
    print(f"History entry count: {len(history)}")
    assert len(history) > 0
    print("History test PASSED")

def main():
    parser = argparse.ArgumentParser(description='NexusStream Pro CLI Testing Tool')
    parser.add_argument('--test-all', action='store_true', help='Run all tests')
    parser.add_argument('--url-test', action='store_true', help='Test URL parsing only')
    parser.add_argument('--history-test', action='store_true', help='Test history functionality')
    
    args = parser.parse_args()
    
    if args.url_test:
        test_url_parsing()
    elif args.history_test:
        test_history()
    elif args.test_all:
        test_url_parsing()
        test_history()
        print("\n=== All Tests Completed ===")
    else:
        print("Use --test-all or specific test flags")
        print("Examples:")
        print("  python nexus_stream_cli.py --test-all")
        print("  python nexus_stream_cli.py --url-test")
        print("  python nexus_stream_cli.py --history-test")

if __name__ == "__main__":
    main()