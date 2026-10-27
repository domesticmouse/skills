# Adding Board Support in Apache NuttX (General & Renesas RA4M1)

## 1. General Board Porting Structure (`nuttx/boards/<arch>/<chip>/<board-name>/`)

Every board package in NuttX resides under `nuttx/boards/<arch>/<chip>/<board-name>/`, is registered in `nuttx/boards/Kconfig`, and is documented in `nuttx/Documentation/platforms/<arch>/<chip>/boards/<board-name>/index.rst`.

### Step 1: Register the Board in `nuttx/boards/Kconfig` (3 Locations)
1. **Board Selection (`choice "Select target board"`)**:
   ```kconfig
   config ARCH_BOARD_<BOARD_UPPER>
   	bool "<Human-Readable Board Name>"
   	depends on ARCH_CHIP_<CHIP>
   	select ARCH_HAVE_LEDS
   	---help---
   		Description of the board, MCU part number, and clock speed.
   ```
2. **Board Folder Mapping (`config ARCH_BOARD`)**:
   ```kconfig
   	default "<board-name>"                 if ARCH_BOARD_<BOARD_UPPER>
   ```
3. **Source the Board Kconfig (at the bottom of `nuttx/boards/Kconfig`)**:
   ```kconfig
   if ARCH_BOARD_<BOARD_UPPER>
   source "boards/<arch>/<chip>/<board-name>/Kconfig"
   endif
   ```

### Step 2: Required Files in `nuttx/boards/<arch>/<chip>/<board-name>/`
```text
nuttx/boards/<arch>/<chip>/<board-name>/
├── Kconfig                      # Board-specific options wrapped in `if ARCH_BOARD_<BOARD_UPPER> ... endif`
├── CMakeLists.txt               # Calls `add_subdirectory(src)`
├── include/
│   └── board.h                  # Clock config, pin muxing macros, LED definitions, GPIO/PWM mappings
├── scripts/
│   ├── Make.defs                # Includes `.config`, `tools/Config.mk`, `<arch>/Toolchain.defs`; sets `ARCHSCRIPT`
│   └── <board-name>.ld          # Linker script defining MEMORY regions (`flash`, `sram`, etc.) and SECTIONS
├── src/
│   ├── Makefile                 # Defines `CSRCS` and includes `$(TOPDIR)/boards/Board.mk`
│   ├── CMakeLists.txt           # Calls `target_sources(board PRIVATE ${SRCS})` and sets `GLOBAL PROPERTY LD_SCRIPT`
│   ├── <board-name>.h           # Internal board header declaring `<chip>_bringup()` and driver init helpers
│   ├── <chip>_boot.c            # Early board init (`<chip>_boardinitialize()`) and `board_late_initialize()`
│   ├── <chip>_bringup.c         # Registers upper-half drivers (`/dev/userleds`, `/dev/gpio*`, `/dev/pwm*`, etc.)
│   ├── <chip>_autoleds.c        # OS diagnostic LED control (built when `CONFIG_ARCH_LEDS=y`)
│   ├── <chip>_userleds.c        # User-space LED driver hooks (built when `CONFIG_ARCH_LEDS=n`)
│   ├── <chip>_gpio.c            # Optional GPIO driver hooks (built when `CONFIG_DEV_GPIO=y`)
│   └── <chip>_pwm.c             # Optional PWM setup hook (built when `CONFIG_PWM=y`)
└── configs/
    └── nsh/
        └── defconfig            # Minimal NSH configuration (`./tools/configure.sh <board-name>:nsh`)
```

### Step 3: Implementation Guidelines & Common Pitfalls
- **All files must carry the Apache-2.0 `SPDX-License-Identifier: Apache-2.0` header** and follow NuttX coding style (`<= 78` chars per line in C/headers, block comments `/* ... */` only, GNU indented braces).
- **Header Guards & Prototypes**:
  - Declare all board driver setup functions (`<chip>_bringup()`, `ra_gpio_initialize()`, `<chip>_pwm_setup()`) in `src/<board-name>.h` and include `"<board-name>.h"` in both `<chip>_bringup.c` and the driver `.c` files rather than scattering `extern` declarations in `.c` files.
- **LED Polarity & Macros in `include/board.h`**:
  - Document and handle active-high vs. active-low (e.g., common-anode RGB LEDs) consistently in `board.h`, `<chip>_autoleds.c`, and `<chip>_userleds.c` (inverting `ledon` in `board_userled()` and `board_userled_all()` for active-low LEDs).
  - Define `LED_STARTED`, `LED_HEAPALLOCATE`, `LED_IRQSENABLED`, `LED_STACKCREATED`, `LED_INIRQ`, `LED_SIGNAL`, `LED_ASSERTION`, `LED_PANIC`, and `LED_IDLE` (avoid duplicate `#define LED_PANIC` lines).
- **Platform Documentation**:
  - Always create `nuttx/Documentation/platforms/<arch>/<chip>/boards/<board-name>/index.rst` documenting the MCU, clock frequency, LEDs and `CONFIG_ARCH_LEDS` states, UART/console pins, PWM/GPIO mappings, and flashing instructions.

---

## 2. Renesas RA4M1 (`arch/arm/src/ra4/`) Specifics

### Supported Reference Boards
- **Seeed Studio XIAO RA4M1**: `nuttx/boards/arm/ra4/xiao-ra4m1/`
- **Arduino UNO R4 Minima**: `nuttx/boards/arm/ra4/arduino-r4-minima/`
- **Arduino Nano R4**: `nuttx/boards/arm/ra4/arduino-nano-r4/`

### Architecture & Chip Layer (`nuttx/arch/arm/src/ra4/`)
- **MCU Variants (`nuttx/arch/arm/src/ra4/Kconfig`)**:
  - `CONFIG_ARCH_CHIP_R7FA4M1ABxxFP`: 100-pin LQFP (SCI0/1/2/9, GPT0–7)
  - `CONFIG_ARCH_CHIP_R7FA4M1ABxxFM`: 64-pin LQFP (SCI0/1/2/9, GPT0–5; used by `xiao-ra4m1`, `arduino-r4-minima`, and `arduino-nano-r4`)
  - `CONFIG_ARCH_CHIP_R7FA4M1ABxxFL`: 48-pin LQFP (SCI0/1/2/9, GPT0–5)
- **Supported Peripherals**:
  - **Clocks** (`ra_clockconfig.c`): Configured via `RA_CKSEL`, `RA_HOCOEN`, `RA_HOCO_FREQUENCY`, and `RA_*CK_DIV` macros in `include/board.h` (typically 64 MHz HOCO).
  - **Pin Multiplexing** (`hardware/ra4m1_pinmap.h`, `ra_gpio.c`): Select alternate pin functions in `include/board.h` (e.g., `GPIO_SCI2_RX`, `GPIO_SCI2_TX`, `GPIO_GPT*_GTIOC*`).
  - **Serial/UART** (`ra_serial.c`): Supports `RA_SCI0_UART`, `RA_SCI1_UART`, `RA_SCI2_UART`, `RA_SCI9_UART`.
  - **PWM / GPT** (`ra_pwm.c`): General Purpose Timers GPT0–7 (`CONFIG_RA_GPT*_PWM`).
  - **Interrupts** (`ra_icu.c`, `hardware/ra4m1_icu.h`): Event Link / ICU interrupt mapping.

### RA4M1 Boot & Linker Details
- **Early Boot Hook**: `ra_start.c` (`nuttx/arch/arm/src/ra4/ra_start.c`) calls `ra_boardinitialize()`, which must be implemented in the board's `src/ra4m1_boot.c`.
- **Memory & ID Code Section**:
  - Flash: `ORIGIN = 0x00000000, LENGTH = 256K`
  - SRAM: `ORIGIN = 0x20000000, LENGTH = 32K`
  - ID Code: `ORIGIN = 0x01010018, LENGTH = 0x20` (`IDCODE1..4` defined as `0xFFFFFFFF` in `include/board.h` and placed in `.id_code`).
  - Because `.id_code` sits at `0x01010018` (outside contiguous flash), enable `CONFIG_INTELHEX_BINARY=y` in `defconfig` and flash `nuttx.hex` (rather than `nuttx.bin`) when using `rfp-cli`:
    ```bash
    rfp-cli -device ra -port /dev/ttyACM0 -p ./nuttx.hex
    ```
  - If targeting a board with a pre-installed bootloader at `0x00000000` (e.g., BOSSA on Arduino UNO R4 / Nano R4 when not overwriting flash via Renesas USB Boot or SWD), adjust the `flash` origin in `<board-name>.ld` accordingly.

---

## 3. Board Validation & Verification Checklist

Always run all three checks after creating or modifying a board port:

1. **Coding Style Check (`checkpatch.sh`)**:
   ```bash
   ./nuttx/tools/checkpatch.sh -f \
     nuttx/boards/<arch>/<chip>/<board-name>/include/board.h \
     nuttx/boards/<arch>/<chip>/<board-name>/src/*.c \
     nuttx/boards/<arch>/<chip>/<board-name>/src/*.h
   ```
2. **Configuration Discovery Check**:
   ```bash
   ./nuttx/tools/configure.sh -L | grep <board-name>
   ```
3. **Compilation Check**:
   - **Full Build** (when `kconfiglib` or `kconfig-conf` is installed):
     ```bash
     cmake -S nuttx -B /tmp/build-<board-name> -DBOARD_CONFIG=<board-name>:nsh -GNinja
     cmake --build /tmp/build-<board-name>
     ```
   - **Standalone Syntax & Warning Verification** (fallback when `kconfiglib`/`kconfig-conf` is not installed on the host, checking both `CONFIG_ARCH_LEDS=1` and `CONFIG_USERLED_LOWER=1` + GPIO/PWM branches):
     ```bash
     rm -rf /tmp/mockinc && mkdir -p /tmp/mockinc/nuttx && \
     cp -R nuttx/arch/arm/include /tmp/mockinc/arch && \
     mkdir -p /tmp/mockinc/arch/board /tmp/mockinc/arch/chip && \
     touch /tmp/mockinc/nuttx/config.h && \
     ln -sf "$PWD/nuttx/boards/arm/ra4/<board-name>/include/board.h" /tmp/mockinc/arch/board/board.h && \
     ln -sf "$PWD/nuttx/arch/arm/include/ra4/chip.h" /tmp/mockinc/arch/chip/chip.h && \
     ln -sf "$PWD/nuttx/arch/arm/include/ra4/irq.h" /tmp/mockinc/arch/chip/irq.h && \
     ln -sf "$PWD/nuttx/arch/arm/include/armv7-m/irq.h" /tmp/mockinc/arch/irq.h && \
     for f in nuttx/boards/arm/ra4/<board-name>/src/*.c; do
       arm-none-eabi-gcc -fsyntax-only -Wall -Werror -Wno-address -D__NuttX__ \
         -DCONFIG_RA4M1_FAMILY=1 -DCONFIG_ARCH_CHIP_R7FA4M1ABxxFM=1 -DCONFIG_ARCH_HAVE_LEDS=1 \
         -DCONFIG_LIBC_MAX_EXITFUNS=1 -DCONFIG_TASK_NAME_SIZE=32 \
         -DCONFIG_NFILE_DESCRIPTORS_PER_BLOCK=8 -DCONFIG_STREAM_OUT_BUFFER_SIZE=64 \
         -DCONFIG_STREAM_HEXDUMP_BUFFER_SIZE=128 -DCONFIG_STREAM_BASE64_BUFFER_SIZE=128 \
         -DCONFIG_USERLED_LOWER=1 -DCONFIG_DEV_GPIO=1 -DCONFIG_PWM=1 -DCONFIG_RA_PWM=1 \
         -DCONFIG_BOARD_LATE_INITIALIZE=1 \
         -I/tmp/mockinc -Inuttx/include -Inuttx/arch/arm/include -Inuttx/arch/arm/include/ra4 \
         -Inuttx/arch/arm/include/armv7-m -Inuttx/arch/arm/src/common \
         -Inuttx/arch/arm/src/armv7-m -Inuttx/arch/arm/src/ra4 \
         -Inuttx/boards/arm/ra4/<board-name>/include -Inuttx/boards/arm/ra4/<board-name>/src \
         "$f" || exit 1
       arm-none-eabi-gcc -fsyntax-only -Wall -Werror -Wno-address -D__NuttX__ \
         -DCONFIG_RA4M1_FAMILY=1 -DCONFIG_ARCH_CHIP_R7FA4M1ABxxFM=1 -DCONFIG_ARCH_HAVE_LEDS=1 \
         -DCONFIG_LIBC_MAX_EXITFUNS=1 -DCONFIG_TASK_NAME_SIZE=32 \
         -DCONFIG_NFILE_DESCRIPTORS_PER_BLOCK=8 -DCONFIG_STREAM_OUT_BUFFER_SIZE=64 \
         -DCONFIG_STREAM_HEXDUMP_BUFFER_SIZE=128 -DCONFIG_STREAM_BASE64_BUFFER_SIZE=128 \
         -DCONFIG_ARCH_LEDS=1 -DCONFIG_BOARD_LATE_INITIALIZE=1 \
         -I/tmp/mockinc -Inuttx/include -Inuttx/arch/arm/include -Inuttx/arch/arm/include/ra4 \
         -Inuttx/arch/arm/include/armv7-m -Inuttx/arch/arm/src/common \
         -Inuttx/arch/arm/src/armv7-m -Inuttx/arch/arm/src/ra4 \
         -Inuttx/boards/arm/ra4/<board-name>/include -Inuttx/boards/arm/ra4/<board-name>/src \
         "$f" || exit 1
     done && rm -rf /tmp/mockinc
     ```
