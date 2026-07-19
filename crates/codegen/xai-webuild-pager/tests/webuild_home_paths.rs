//! `WEBUILD_HOME` override tests in an isolated binary so `webuild_home()`'s
//! process-wide `OnceLock` initializes from the overridden env var.

use std::path::PathBuf;

#[test]
fn webuild_home_override_path_helpers() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let webuild_home = tmp.path().to_path_buf();
    unsafe {
        std::env::set_var("WEBUILD_HOME", &webuild_home);
    }

    assert_eq!(
        xai_webuild_pager::util::pager_toml_path(),
        webuild_home.join("pager.toml")
    );
    assert_eq!(
        xai_webuild_pager::util::display_webuild_home_prefix(),
        "$WEBUILD_HOME"
    );
    assert_eq!(
        xai_webuild_pager::util::display_user_webuild_path("config.toml"),
        "$WEBUILD_HOME/config.toml"
    );

    let memory_path = webuild_home.join("memory/MEMORY.md");
    assert_eq!(
        xai_webuild_pager::util::abbreviate_path(&memory_path.display().to_string()),
        "$WEBUILD_HOME/memory/MEMORY.md"
    );

    assert!(xai_webuild_pager::util::is_under_user_webuild_home(&memory_path));
    assert!(!xai_webuild_pager::util::is_under_user_webuild_home(
        PathBuf::from("/tmp/other").as_path()
    ));
}
