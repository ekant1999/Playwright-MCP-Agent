#!/bin/bash
# Test all MCP flows via bridge server. Run with bridge server already running.
# Usage: ./test_flows.sh [base_url]
set -e
BASE="${1:-http://localhost:3001}"

echo "=== Testing flows (bridge: $BASE) ==="

# 1. arXiv search (no browser)
echo -n "1. arXiv search... "
R=$(curl -s -X POST "$BASE/tools/call" -H "Content-Type: application/json" \
  -d '{"name":"arxiv_search","arguments":{"query":"machine learning","max_results":2}}')
if echo "$R" | grep -q '"success":true' && echo "$R" | grep -q 'status.*success'; then
  echo "OK"
else
  echo "FAIL"
  echo "$R" | head -1
fi

# 2. arXiv get paper (use real ID from search)
echo -n "2. arXiv get_paper... "
R=$(curl -s -X POST "$BASE/tools/call" -H "Content-Type: application/json" \
  -d '{"name":"arxiv_get_paper","arguments":{"paper_id":"2306.04338"}}')
if echo "$R" | grep -q '"success":true' && echo "$R" | grep -q 'arxiv_id'; then
  echo "OK"
else
  echo "FAIL"
fi

# 3. arXiv download PDF (saves to downloads/)
echo -n "3. arXiv download_pdf... "
R=$(curl -s -X POST "$BASE/tools/call" -H "Content-Type: application/json" \
  -d '{"name":"arxiv_download_pdf","arguments":{"paper_id":"2306.04338"}}')
if echo "$R" | grep -q '"success":true' && echo "$R" | grep -q 'filename'; then
  echo "OK"
else
  echo "FAIL"
fi

# 4. Health + tools list
echo -n "4. Health... "
H=$(curl -s "$BASE/health")
if echo "$H" | grep -q '"mcp_connected":true'; then
  echo "OK"
else
  echo "FAIL"
fi

echo -n "5. Tools list... "
T=$(curl -s "$BASE/tools")
if echo "$T" | grep -q '"name":'; then
  echo "OK"
else
  echo "FAIL"
fi

echo ""
echo "Browser-dependent flows (browser_launch, search_web, navigate, get_content, screenshot, ieee_*)"
echo "must be tested from the UI at http://localhost:5173"
echo "On Mac M1/M2 ensure arm64 Chromium is installed: PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers playwright install chromium"
