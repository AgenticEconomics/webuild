fn main() {
    println!("cargo:rerun-if-env-changed=WEBUILD_VERSION");
}
