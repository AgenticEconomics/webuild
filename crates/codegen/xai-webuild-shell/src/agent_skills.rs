//! Phase VI: vendored AgenticEconomics/skills marketplace sync + install.
//!
//! Resolves the on-disk marketplace root, syncs it into
//! `~/.webuild/marketplaces/agent-skills`, registers a local marketplace
//! source, and installs the `default-skills` plugin so the 17 imported
//! skills are available without manual `/plugins` steps.

use std::path::{Path, PathBuf};

use xai_webuild_agent::plugins::install_registry::{InstallRegistry, MarketplaceProvenance};
use xai_webuild_plugin_marketplace::installer;

/// Marketplace source display name in config.toml.
pub const AGENT_SKILLS_SOURCE_NAME: &str = "WeBuild Agent Skills";

/// Plugin subdir auto-installed from the marketplace root.
pub const AGENT_SKILLS_PLUGIN_SUBDIR: &str = "default-skills";

/// Sandbox / packaged install location.
pub const AGENT_SKILLS_OPT_PATH: &str = "/opt/webuild/agent-skills";

const SYNC_MARKER: &str = ".webuild-sync-version";

/// Resolve the vendor marketplace root (must contain `default-skills/`).
pub fn resolve_agent_skills_root() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("WEBUILD_AGENT_SKILLS_ROOT") {
        let path = PathBuf::from(p);
        if is_valid_marketplace(&path) {
            return Some(path);
        }
    }

    let opt = PathBuf::from(AGENT_SKILLS_OPT_PATH);
    if is_valid_marketplace(&opt) {
        return Some(opt);
    }

    if let Some(compiled) = option_env!("WEBUILD_AGENT_SKILLS_SRC") {
        let path = PathBuf::from(compiled);
        if is_valid_marketplace(&path) {
            return Some(path);
        }
    }

    None
}

fn is_valid_marketplace(root: &Path) -> bool {
    root.join("default-skills").is_dir()
        && std::fs::read_dir(root.join("default-skills"))
            .ok()
            .map(|rd| {
                rd.filter_map(|e| e.ok())
                    .any(|e| e.path().join("SKILL.md").exists())
            })
            .unwrap_or(false)
}

/// Read upstream commit / version string used as sync marker.
pub fn marketplace_version(root: &Path) -> String {
    // Prefer SOURCE.md commit line; fall back to marketplace.json metadata.
    if let Ok(src) = std::fs::read_to_string(root.join("SOURCE.md")) {
        for line in src.lines() {
            if let Some(rest) = line.strip_prefix("- Imported commit:") {
                let sha = rest
                    .trim()
                    .trim_matches('`')
                    .trim()
                    .split_whitespace()
                    .next()
                    .unwrap_or("");
                if !sha.is_empty() {
                    return sha.to_string();
                }
            }
        }
    }
    if let Ok(raw) = std::fs::read_to_string(root.join(".webuild-plugin/marketplace.json"))
        && let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw)
        && let Some(commit) = v
            .pointer("/metadata/upstream_commit")
            .and_then(|c| c.as_str())
    {
        return commit.to_string();
    }
    "unknown".to_string()
}

/// Sync vendor tree → `~/.webuild/marketplaces/agent-skills` when version differs.
pub fn sync_agent_skills_marketplace(
    source_root: &Path,
    dest_root: &Path,
) -> std::io::Result<bool> {
    let version = marketplace_version(source_root);
    let marker = dest_root.join(SYNC_MARKER);
    if marker.is_file()
        && let Ok(existing) = std::fs::read_to_string(&marker)
        && existing.trim() == version
        && is_valid_marketplace(dest_root)
    {
        return Ok(false);
    }

    if dest_root.exists() {
        std::fs::remove_dir_all(dest_root)?;
    }
    copy_dir_recursive(source_root, dest_root)?;
    std::fs::write(&marker, &version)?;
    Ok(true)
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_recursive(&from, &to)?;
        } else if ty.is_symlink() {
            // Skip symlinks for safety when vendoring.
            continue;
        } else {
            if let Some(parent) = to.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(&from, &to)?;
        }
    }
    Ok(())
}

/// Install (or refresh) the `default-skills` plugin from a marketplace root.
pub fn install_agent_skills_plugin(
    marketplace_root: &Path,
    source_display_path: &str,
) -> Result<String, String> {
    let mut reg = InstallRegistry::load();
    let existing = installer::find_installed_marketplace_plugin(
        &reg,
        source_display_path,
        AGENT_SKILLS_PLUGIN_SUBDIR,
    );
    if let Some((existing_key, _)) = existing {
        let old_dir = reg.install_dir().join(&existing_key);
        let _ = std::fs::remove_dir_all(&old_dir);
        reg.remove(&existing_key);
        let _ = reg.save();
        reg = InstallRegistry::load();
    }

    let provenance = MarketplaceProvenance {
        source_url_or_path: source_display_path.to_string(),
        source_display_name: AGENT_SKILLS_SOURCE_NAME.to_string(),
        plugin_subdir: AGENT_SKILLS_PLUGIN_SUBDIR.to_string(),
    };

    match installer::install_from_marketplace(
        marketplace_root,
        AGENT_SKILLS_PLUGIN_SUBDIR,
        provenance,
        &mut reg,
    ) {
        Ok(installer::MarketplaceInstallResult::Installed { repo_key })
        | Ok(installer::MarketplaceInstallResult::AlreadyInstalled { repo_key }) => Ok(repo_key),
        Err(e) => Err(format!("{e:?}")),
    }
}

/// Full Phase VI ensure: sync + register marketplace source + install plugin.
///
/// Best-effort; never panics. Skips when no vendor root is available.
pub fn ensure_agent_skills(webuild_home: &Path) {
    let Some(source_root) = resolve_agent_skills_root() else {
        tracing::debug!(
            "agent skills marketplace not found (set WEBUILD_AGENT_SKILLS_ROOT or install to {})",
            AGENT_SKILLS_OPT_PATH
        );
        return;
    };

    let dest_root = webuild_home.join("marketplaces").join("agent-skills");
    let synced = match sync_agent_skills_marketplace(&source_root, &dest_root) {
        Ok(true) => {
            tracing::info!(
                from = %source_root.display(),
                to = %dest_root.display(),
                "synced WeBuild Agent Skills marketplace"
            );
            true
        }
        Ok(false) => false,
        Err(e) => {
            tracing::warn!(
                error = %e,
                from = %source_root.display(),
                "failed to sync agent skills marketplace"
            );
            return;
        }
    };

    if !is_valid_marketplace(&dest_root) {
        tracing::warn!(
            path = %dest_root.display(),
            "agent skills marketplace sync produced invalid tree"
        );
        return;
    }

    let dest_str = dest_root.display().to_string();
    let config_path = webuild_home.join("config.toml");
    if let Err(e) = crate::extensions::marketplace::add_agent_skills_marketplace_source(
        &config_path,
        &dest_root,
    ) {
        tracing::warn!(error = %e, "failed to register agent skills marketplace source");
    }

    let need_install = synced || {
        let reg = InstallRegistry::load();
        installer::find_installed_marketplace_plugin(
            &reg,
            &dest_str,
            AGENT_SKILLS_PLUGIN_SUBDIR,
        )
        .is_none()
    };

    let repo_key = if need_install {
        match install_agent_skills_plugin(&dest_root, &dest_str) {
            Ok(repo_key) => {
                tracing::info!(
                    repo_key = %repo_key,
                    "installed/refreshed WeBuild Agent Skills (default-skills)"
                );
                Some(repo_key)
            }
            Err(e) => {
                tracing::warn!(error = %e, "failed to install agent skills plugin");
                None
            }
        }
    } else {
        // Already installed — still resolve repo key so we can ensure it's enabled.
        let reg = InstallRegistry::load();
        installer::find_installed_marketplace_plugin(
            &reg,
            &dest_str,
            AGENT_SKILLS_PLUGIN_SUBDIR,
        )
        .map(|(key, _)| key)
    };

    // User-scope marketplace plugins are disabled by default until listed in
    // `[plugins].enabled`. Without this, `/skills` only shows bundled skills.
    if let Some(repo_key) = repo_key {
        let (names, warnings) = crate::config::post_install_plugin(&repo_key);
        if !names.is_empty() {
            tracing::info!(
                plugins = ?names,
                "enabled WeBuild Agent Skills plugin(s)"
            );
        }
        for w in warnings {
            tracing::warn!(warning = %w, "agent skills auto-enable warning");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_minimal_skill(root: &Path, name: &str) {
        let dir = root.join("default-skills").join(name);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(
            dir.join("SKILL.md"),
            format!("---\nname: {name}\ndescription: test\n---\n\n# {name}\n"),
        )
        .unwrap();
    }

    #[test]
    fn is_valid_requires_skill_md() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(!is_valid_marketplace(tmp.path()));
        write_minimal_skill(tmp.path(), "frontend-design");
        assert!(is_valid_marketplace(tmp.path()));
    }

    #[test]
    fn sync_is_idempotent_on_same_version() {
        let src = tempfile::tempdir().unwrap();
        write_minimal_skill(src.path(), "pdf");
        std::fs::write(
            src.path().join("SOURCE.md"),
            "- Imported commit: `abc123`\n",
        )
        .unwrap();

        let dest_parent = tempfile::tempdir().unwrap();
        let dest = dest_parent.path().join("agent-skills");

        assert!(sync_agent_skills_marketplace(src.path(), &dest).unwrap());
        assert!(dest.join("default-skills/pdf/SKILL.md").is_file());
        assert!(!sync_agent_skills_marketplace(src.path(), &dest).unwrap());
    }

    #[test]
    fn marketplace_version_from_source_md() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(
            tmp.path().join("SOURCE.md"),
            "- Imported commit: `deadbeef`\n",
        )
        .unwrap();
        assert_eq!(marketplace_version(tmp.path()), "deadbeef");
    }

    #[test]
    fn install_default_skills_from_temp_marketplace() {
        let src = tempfile::tempdir().unwrap();
        write_minimal_skill(src.path(), "frontend-design");
        write_minimal_skill(src.path(), "mcp-builder");
        std::fs::write(
            src.path().join("SOURCE.md"),
            "- Imported commit: `testha`\n",
        )
        .unwrap();

        let home = tempfile::tempdir().unwrap();
        let dest = home.path().join("marketplaces/agent-skills");
        assert!(sync_agent_skills_marketplace(src.path(), &dest).unwrap());

        let install_dir = home.path().join("plugins-installed");
        std::fs::create_dir_all(&install_dir).unwrap();
        let mut reg = InstallRegistry::empty(install_dir.clone());
        let provenance = MarketplaceProvenance {
            source_url_or_path: dest.display().to_string(),
            source_display_name: AGENT_SKILLS_SOURCE_NAME.to_string(),
            plugin_subdir: AGENT_SKILLS_PLUGIN_SUBDIR.to_string(),
        };
        let result = installer::install_from_marketplace(
            &dest,
            AGENT_SKILLS_PLUGIN_SUBDIR,
            provenance,
            &mut reg,
        )
        .unwrap();
        let repo_key = match result {
            installer::MarketplaceInstallResult::Installed { repo_key }
            | installer::MarketplaceInstallResult::AlreadyInstalled { repo_key } => repo_key,
        };
        let installed = install_dir.join(&repo_key);
        assert!(installed.join("frontend-design/SKILL.md").is_file());
        assert!(installed.join("mcp-builder/SKILL.md").is_file());
        assert!(installed.join("plugin.json").is_file());
    }
}
