# WeBuild Windows note — this fork ships prebuilt Unix binaries via GitHub Releases.
# On Windows, build from source or use WSL:
#   curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash
Write-Host "WeBuild prebuilt installer for native Windows is not published for this fork yet."
Write-Host "Options:"
Write-Host "  1) Use WSL and: curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash"
Write-Host "  2) Build from source: cargo build -p xai-webuild-pager-bin --release"
Write-Host "Repo: https://github.com/AgenticEconomics/webuild"
exit 1
