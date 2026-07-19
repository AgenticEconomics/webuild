//! Shared utilities used by both `xai-webuild-shell` and its downstream clients
//! (e.g. `xai-webuild-pager-render`). This crate sits upstream of `xai-webuild-shell`
//! so it must never depend on it.

pub mod clipboard;
pub mod placeholder_images;
pub mod session;
pub mod stderr;
pub mod ui_config;
