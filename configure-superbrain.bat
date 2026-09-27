@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
)
echo.
echo ============================================================
echo  SuperBrain SB-026 - OSINT + Privacy configuration
echo ============================================================
echo.
echo Model providers:
echo   OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY
echo.
echo Research sources:
echo   GITHUB_TOKEN       optional - increases GitHub API access
 echo  TAVILY_API_KEY     optional
 echo  BRAVE_SEARCH_API_KEY optional
 echo  SUPERBRAIN_RESEARCH_SOURCES=web,github,duckduckgo
 echo.
echo Privacy egress:
echo   direct      = normal connection
 echo  http_proxy = explicit HTTP CONNECT proxy
 echo  socks5     = explicit SOCKS5 proxy
 echo  tor        = SOCKS5/Tor with remote DNS and onion allowlist
 echo.
echo Tor Browser commonly exposes a local SOCKS port at 9150; a Tor daemon commonly uses 9050.
echo Set SUPERBRAIN_ONION_ALLOWLIST to explicit .onion hostnames before onion research.
echo.
echo Stealth mode is enabled by default: loopback-only + API authentication.
echo.
start "" notepad "%CD%\.env"
endlocal
