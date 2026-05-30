// Prevents an extra console window on Windows in release. No effect on macOS/Linux.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    agents_desktop_lib::run()
}
