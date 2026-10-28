---
name: nuttx-architecture
description: >-
  Architectural guide and development workflows for the Apache NuttX RTOS (`nuttx`)
  and application suite (`apps`) repositories. Use this skill when navigating,
  configuring, building, debugging, or adding drivers, boards, kernel features,
  or user-space applications in NuttX.
---

## 1. Core Architectural Principles (`nuttx/INVIOLABLES.md`)

1. **Strict POSIX & ANSI Compliance**: Prefer standard POSIX APIs (`open`, `read`, `write`, `ioctl`, `poll`, `pthread`, BSD sockets, POSIX timers/mqueues) over custom APIs.
2. **Modular Layering**:
   - **Upper-Half Drivers (`nuttx/drivers/`)**: Architecture-independent driver logic that registers VFS character/block devices (e.g., `/dev/ttyS0`, `/dev/spi0`) and handles locking/buffering.
   - **Lower-Half Drivers (`nuttx/arch/` or `nuttx/boards/`)**: SoC- or board-specific hardware implementation passed to the upper half via an ops vtable.
   - **Internal Porting Interface (`up_*`)**: Defined in `nuttx/include/nuttx/arch.h` for CPU/SoC operations and `nuttx/include/nuttx/board.h` for board-level initialization.
3. **Three Build Modes**:
   - `CONFIG_BUILD_FLAT`: Unprotected flat address space (single binary).
   - `CONFIG_BUILD_PROTECTED`: MPU-isolated user (`apps`) and kernel (`nuttx`) spaces bridged via `nuttx/syscall/`.
   - `CONFIG_BUILD_KERNEL`: MMU-isolated virtual address spaces (`nuttx/sched/addrenv/`); user processes loaded dynamically via `nuttx/binfmt/`.

---

## 2. Configuration & Build Workflows

Always run configuration and build commands from the `nuttx/` directory (or specify `-S nuttx -B build` for CMake).

### Option A: CMake + Ninja (Recommended for Fast Incremental Builds)

1. Ensure `nuttx/.config` does not exist from a previous Make build (`make -C nuttx distclean` if needed).
2. Configure a `<board>:<config>` target (e.g., `sim:nsh`):
   ```bash
   cmake -S nuttx -B build -DBOARD_CONFIG=sim:nsh -GNinja
   ```
3. Build:
   ```bash
   cmake --build build
   ```
4. Reconfigure via menuconfig (if needed):
   ```bash
   cmake --build build -t menuconfig
   ```

### Option B: GNU Make

1. Configure `<board>:<config>`:
   ```bash
   cd nuttx && ./tools/configure.sh sim:nsh
   ```
   *(List all available board configs with `./tools/configure.sh -L`.)*
2. Build:
   ```bash
   make -C nuttx -j$(sysctl -n hw.ncpu 2>/dev/null || nproc)
   ```
3. Clean / Distclean:
   ```bash
   make -C nuttx clean      # Keep .config, remove objects
   make -C nuttx distclean  # Remove .config and all generated files
   ```

---

## 3. Common Development Tasks

### Adding or Modifying a Driver
1. Check `nuttx/include/nuttx/` for the subsystem's upper-half interface header (e.g., `nuttx/serial/serial.h`, `nuttx/sensors/sensor.h`, `nuttx/spi/spi.h`).
2. Keep hardware register manipulation strictly in `nuttx/arch/<arch>/src/<chip>/` and board pin/clock wiring in `nuttx/boards/<arch>/<chip>/<board>/src/`.
3. Expose portable upper-half driver logic in `nuttx/drivers/<subsystem>/` and wire it into `Kconfig`, `Make.defs`, and `CMakeLists.txt`.

### Adding a New Board (e.g., Renesas RA4M1)
1. **Register in `nuttx/boards/Kconfig`** in 3 places:
   - `config ARCH_BOARD_<BOARD_UPPER>` inside the target board `choice` block (select `ARCH_HAVE_LEDS` if the board has controllable LEDs).
   - `default "<board-name>" if ARCH_BOARD_<BOARD_UPPER>` under `config ARCH_BOARD`.
   - `if ARCH_BOARD_<BOARD_UPPER>` / `source "boards/<arch>/<chip>/<board-name>/Kconfig"` / `endif` at the bottom.
2. **Create `nuttx/boards/<arch>/<chip>/<board-name>/`** containing:
   - `Kconfig` and `CMakeLists.txt`
   - `include/board.h` (clocks, pin muxing, active-high/low LED definitions, GPIO/PWM mappings)
   - `scripts/Make.defs` and `scripts/<board-name>.ld`
   - `src/` (`Makefile`, `CMakeLists.txt`, `<board-name>.h`, `<chip>_boot.c`, `<chip>_bringup.c`, `<chip>_autoleds.c`, `<chip>_userleds.c`, and optional `<chip>_gpio.c` / `<chip>_pwm.c`)
   - `configs/nsh/defconfig`
3. **Add Documentation**: Create `nuttx/Documentation/platforms/<arch>/<chip>/boards/<board-name>/index.rst` covering MCU specs, pin mappings (LEDs, UART, PWM, GPIO), and flashing instructions.
4. **Validate**: Run `checkpatch.sh` on all `.c`/`.h` files, verify config discovery with `./nuttx/tools/configure.sh -L | grep <board-name>`, and compile-check both `CONFIG_ARCH_LEDS` and `CONFIG_USERLED_LOWER` + driver branches.
5. See [Board Porting & RA4M1 Reference](./references/board_porting_and_ra4m1.md) for the complete step-by-step guide, RA4M1 specifics (`R7FA4M1ABxxFP`/`FM`/`FL`, `ra4m1_pinmap.h`, `.id_code` section), and standalone compiler verification when `kconfiglib`/`kconfig-conf` is not installed.

### Adding a User-Space Built-In Application
1. Create `apps/<category>/<appname>/` with:
   - `Kconfig` (defining `CONFIG_<CATEGORY>_<APPNAME>`)
   - `Make.defs` (appending `CONFIGURED_APPS += $(APPDIR)/<category>/<appname>` when enabled)
   - `Makefile` (setting `PROGNAME`, `PRIORITY`, `STACKSIZE`, `MAINSRC`, and including `$(APPDIR)/Application.mk`)
   - `CMakeLists.txt` (calling `nuttx_add_application(...)`)
2. See [Apps & NSH Reference](./references/apps_and_nsh.md) for complete templates.

---

## 4. Validation & Coding Standard Checks

NuttX enforces a strict C89/C99 coding standard (indented GNU-style braces, block comments `/* ... */`, explicit `FAR`/`CODE` annotations where applicable).

1. **Run `checkpatch.sh` before finishing any code changes**:
   ```bash
   ./nuttx/tools/checkpatch.sh -f <path/to/modified_file.c> <path/to/header.h>
   ```
   *(Note: Only pass `.c` and `.h` files if `cmake-format` is not installed on the host, as `checkpatch.sh` invokes `cmake-format` on `CMakeLists.txt`.)*
   Or check the latest git commit / working tree diff:
   ```bash
   git -C nuttx diff | ./nuttx/tools/checkpatch.sh -
   ```
2. **Verify Configuration Discovery**:
   ```bash
   ./nuttx/tools/configure.sh -L | grep <board-name>
   ```
3. **Verify Compilation**: Build the affected board config (or `sim:nsh` for generic kernel/app changes) and ensure zero compiler warnings. If `kconfiglib` or `kconfig-conf` is unavailable on the host, run the standalone `arm-none-eabi-gcc -fsyntax-only -Wall -Werror` verification documented in [Board Porting & RA4M1 Reference](./references/board_porting_and_ra4m1.md#3-board-validation--verification-checklist).

---

## 5. Detailed References

Load these references on demand when working in specific areas:
- [Kernel Subsystems & Boot Flow (`nuttx/`)](./references/kernel_subsystems.md)
- [Board Porting & Renesas RA4M1 (`nuttx/boards/`)](./references/board_porting_and_ra4m1.md)
- [User-Space Applications & NuttShell (`apps/`)](./references/apps_and_nsh.md)
