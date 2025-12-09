use pyo3_build_config::{add_extension_module_link_args, get, use_pyo3_cfgs};

fn main() {
    add_extension_module_link_args();
    let config = get();

    if let Some(lib_dir) = config.lib_dir.as_deref() {
        println!("cargo:rustc-link-search=native={}", lib_dir);
    }
    if let Some(lib_name) = config.lib_name.as_deref() {
        println!("cargo:rustc-link-lib=dylib={}", lib_name);
    }

    use_pyo3_cfgs();
}
