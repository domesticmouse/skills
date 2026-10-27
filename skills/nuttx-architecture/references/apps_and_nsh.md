# NuttX Applications & NuttShell Reference (`apps/`)

## 1. Directory Map

| Directory | Purpose |
| :--- | :--- |
| `nshlib/` | Core NuttShell (NSH) library implementing command parsing, built-in shell commands (`ls`, `mount`, `ps`, `free`, `ifconfig`, etc.), init script execution (`rc.sysinit`, `rcS`), and serial/USB/Telnet sessions. |
| `system/` | System utilities and CLI tools (`nsh`, `adb`, `fastboot`, `i2c`, `spi`, `ping`, `ping6`, `tcpdump`, `gdbstub`, `trace`, `ymodem`, `dd`, `vi`, `taskset`, etc.). |
| `builtin/` | Registry and execution engine (`exec_builtin()`) that maps string command names to C entry points in flat and protected builds. |
| `netutils/` | Network libraries, clients, and daemons (`netlib`, `dhcpc`, `dhcpd`, `mqttc`, `iperf`, `ntpclient`, `telnetd`, `webserver`, `cjson`, `rexec`, etc.). |
| `fsutils/` | Filesystem formatting and flash utilities (`mkfatfs`, `mkgpt`, `mksmartfs`, `flash_eraseall`, `inih`, `ipcfg`). |
| `testing/` | OS and subsystem test suites (`ostest`, `cmocka`, `ltp`, `mm`, `fstest`, `drivertest`, `schedtest`). |
| `benchmarks/` | Performance benchmarks (`coremark`, `dhrystone`, `ramspeed`, `iozone`, `osperf`, `superpi`). |
| `examples/` | 240+ reference applications demonstrating POSIX APIs, peripherals, networking, and drivers (`examples/hello` is the canonical skeleton). |
| `graphics/` | LVGL (`lvgl`), NxWidgets, NxWM, and graphics helpers. |
| `interpreters/` | Embedded language runtimes (`wamr`, `quickjs`, `lua`, `micropython`, `duktape`, `bas`, `forth`). |
| `mlearning/` | Machine learning libraries (`tflite-micro`, `cmsis-nn`, `libnnablart`). |
| `crypto/` / `boot/` / `tee/` | Security & bootloader apps (`mbedtls`, `tinycrypt`, `libsodium`, `mcuboot`, `optee`). |
| `audioutils/` / `videoutils/` / `wireless/` / `canutils/` / `industry/` / `inertial/` / `sdr/` / `lte/` | Domain-specific libraries and utilities. |

---

## 2. How `apps/` Integrates with `nuttx/`

1. **Auto-Discovery**: `apps/Makefile` and `apps/tools/mkkconfig.sh` wildcard-scan subdirectories containing `Make.defs` and `Kconfig`. No central list in `apps/` needs manual editing when adding a new top-level or external app folder.
2. **Built-In Registration**: When an application sets `PROGNAME`, `PRIORITY`, `STACKSIZE`, and `MAINSRC` in its `Makefile` (and includes `$(APPDIR)/Application.mk`) or calls `nuttx_add_application()` in `CMakeLists.txt`, the build registers its entry point into `builtin_list.h` and `builtin_proto.h`.
3. **Executing Built-Ins from NSH**: With `CONFIG_NSH_BUILTIN_APPS=y`, typing `<PROGNAME>` at the `nsh>` prompt spawns the registered task via `exec_builtin()`.

---

## 3. Skeleton for a New Application (`apps/examples/my_app/`)

### `Kconfig`
```kconfig
config EXAMPLES_MY_APP
	tristate "\"My App\" example"
	default n
	---help---
		Enable the My App example

if EXAMPLES_MY_APP

config EXAMPLES_MY_APP_PROGNAME
	string "Program name"
	default "my_app"

config EXAMPLES_MY_APP_PRIORITY
	int "My App task priority"
	default 100

config EXAMPLES_MY_APP_STACKSIZE
	int "My App stack size"
	default DEFAULT_TASK_STACKSIZE

endif
```
*(Remember to `source` the new `Kconfig` in the parent directory's `Kconfig` if placing it inside an existing category like `apps/examples/Kconfig`.)*

### `Make.defs`
```makefile
ifneq ($(CONFIG_EXAMPLES_MY_APP),)
CONFIGURED_APPS += $(APPDIR)/examples/my_app
endif
```

### `Makefile`
```makefile
include $(APPDIR)/Make.defs

PROGNAME  = $(CONFIG_EXAMPLES_MY_APP_PROGNAME)
PRIORITY  = $(CONFIG_EXAMPLES_MY_APP_PRIORITY)
STACKSIZE = $(CONFIG_EXAMPLES_MY_APP_STACKSIZE)
MODULE    = $(CONFIG_EXAMPLES_MY_APP)

MAINSRC = my_app_main.c

include $(APPDIR)/Application.mk
```

### `CMakeLists.txt`
```cmake
if(CONFIG_EXAMPLES_MY_APP)
  nuttx_add_application(
    NAME
    ${CONFIG_EXAMPLES_MY_APP_PROGNAME}
    SRCS
    my_app_main.c
    STACKSIZE
    ${CONFIG_EXAMPLES_MY_APP_STACKSIZE}
    PRIORITY
    ${CONFIG_EXAMPLES_MY_APP_PRIORITY}
    MODULE
    ${CONFIG_EXAMPLES_MY_APP})
endif()
```

---

## 4. Out-of-Tree Customizations

- **`apps/external` Symlink**: Symlink an external directory to `apps/external` (which is git-ignored in `apps/.gitignore`). Provide `Make.defs`, `Makefile`, `Kconfig`, and `CMakeLists.txt` inside `apps/external` to seamlessly include out-of-tree apps.
- **Custom Application Root (`CONFIG_APPS_DIR`)**: Pass `-a <custom-app-dir>` to `tools/configure.sh` or `-DNUTTX_APPS_DIR=<custom-app-dir>` to CMake.
- **SDK Export (`make export`)**: Run `make export` in `nuttx/` to bundle compiled kernel/library archives (`.a`), headers, and startup objects into a standalone `.zip` archive for external build systems.
