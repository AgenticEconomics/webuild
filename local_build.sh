# Build one platform yourself
cargo build -p xai-webuild-pager-bin --release  &&
cp target/release/xai-webuild-pager /tmp/webuild-linux-x86_64 &&

# Manual install path users effectively get:
mkdir -p ~/.webuild/bin &&
cp /tmp/webuild-linux-x86_64 ~/.webuild/bin/webuild &&
chmod +x ~/.webuild/bin/webuild &&
export PATH="$HOME/.webuild/bin:$PATH" &&

# Test the installation
webuild --version
