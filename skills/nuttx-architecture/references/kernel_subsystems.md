# NuttX Kernel Subsystems & Boot Sequence (`nuttx/`)

## 1. Directory Map

| Directory | Purpose |
| :--- | :--- |
| `arch/` | CPU & SoC Hardware Abstraction Layer (`arm`, `arm64`, `risc-v`, `xtensa`, `x86_64`, `sim`, `avr`, `z80`, `tricore`, `sparc`, `mips`, `or1k`, `renesas`, `ceva`). Implements `up_*` APIs declared in `include/nuttx/arch.h`. |
| `boards/` | Board-specific packages (`boards/<arch>/<chip>/<board>/`), linker scripts (`scripts/`), board initialization (`src/`), and `configs/<config>/defconfig` presets. |
| `sched/` | Core RTOS kernel: boot (`init/`), task/thread management (`task/`, `pthread/`, `group/`), scheduler (`sched/`), IRQs (`irq/`), synchronization (`semaphore/`, `event/`, `mqueue/`, `signal/`), timers/clocks (`clock/`, `timer/`, `hrtimer/`, `wdog/`), work queues (`wqueue/`), and virtual address environments (`addrenv/`). |
| `drivers/` | Portable upper-half device drivers (`serial`, `spi`, `i2c`, `i3c`, `can`, `sensors`, `mtd`, `mmcsd`, `usbdev`, `usbhost`, `net`, `video`, `wireless`, `virtio`, `rpmsg`, `rptun`, `syslog`, `timers`, `power`, `motor`, etc.). |
| `fs/` | Virtual File System (`vfs/`, `inode/`, `mount/`, `driver/`) and filesystem implementations (`littlefs`, `fat`, `romfs`, `cromfs`, `tmpfs`, `procfs`, `smartfs`, `spiffs`, `nxffs`, `mnemofs`, `hostfs`, `rpmsgfs`, `nfs`, `v9fs`, `zipfs`, `binfs`). |
| `mm/` | Memory managers: standard heap (`mm_heap`), TLSF (`tlsf`), granule/page allocator (`mm_gran`), fixed-size pools (`mempool`), I/O buffers (`iob`), kernel dynamic mapping (`kmap`), shared memory (`shm`), and sanitizers (`kasan`, `ubsan`). |
| `net/` | Native BSD socket stack (`socket/`, `inet/`, `tcp/`, `udp/`, `icmp/`, `icmpv6/`, `arp/`, `igmp/`, `mld/`, `route/`, `nat/`, `netfilter/`, `sixlowpan/`, `can/`, `bluetooth/`, `ieee802154/`, `netlink/`, `rpmsg/`, `usrsock/`). |
| `libs/` | Standard C library (`libc`), math (`libm`), C++ runtime (`libxx`), DSP (`libdsp`), graphics (`libnx`), and compiler builtins (`libbuiltin`). |
| `syscall/` | System call proxy/stub generation (`syscall.csv`) for `CONFIG_BUILD_PROTECTED` and `CONFIG_BUILD_KERNEL`. |
| `binfmt/` | Binary loaders (`elf`, `nxflat`, `builtin`, `symtab`) for executing programs from filesystems. |
| `openamp/` | OpenAMP / Libmetal integration for heterogeneous multi-core RPMsg communication. |
| `crypto/` | Kernel cryptographic subsystem and hardware crypto API (`/dev/crypto`). |
| `audio/` / `video/` / `graphics/` / `wireless/` | Subsystem core frameworks shared with their respective drivers in `drivers/`. |
| `include/` | System-wide POSIX/ANSI headers (`include/sys/`, `include/arpa/`, etc.) and internal NuttX headers (`include/nuttx/`). |
| `tools/` | Configuration scripts (`configure.sh`, `kconfig2cmake.py`), style checker (`checkpatch.sh`, `nxstyle.c`), and Make infrastructure (`Unix.mk`, `Win.mk`, `Config.mk`). |

---

## 2. Kernel Boot Sequence (`sched/init/nx_start.c`)

Low-level reset code in `arch/<arch>/` initializes stack/BSS and jumps to `nx_start()`, which advances `g_nx_initstate` through 6 phases:

1. **`OSINIT_BOOT`**:
   - `tasklist_initialize()` sets up prioritized ready-to-run and wait queues (`g_readytorun`, `g_pendingtasks`, `g_assignedtasks`).
   - `idle_task_initialize()` initializes `g_idletcb[0..CONFIG_SMP_NCPUS-1]` (PID 0..N-1, priority 0).
2. **`OSINIT_TASKLISTS`**:
   - `drivers_early_initialize()` and `nxsem_initialize()`.
   - Heap initialization: `up_allocate_heap()` / `kumm_initialize()` (user heap), `up_allocate_kheap()` / `kmm_initialize()` (kernel heap), `mm_pginitialize()` (page heap), and `iob_initialize()` (network/IO buffers).
   - Allocates `g_pidhash` and initializes the IDLE task group (`idle_group_initialize()`).
3. **`OSINIT_MEMORY`**:
   - Initializes core facilities: `task_initialize()`, `fs_initialize()`, `irq_initialize()`, `clock_initialize()`, `timer_initialize()`, `nxsig_initialize()`, `nxmq_initialize()`, `net_initialize()`, `binfmt_initialize()`.
   - Calls `up_initialize()` (architecture interrupt/timer/DMA/serial init), `drivers_initialize()` (common drivers in `drivers/drivers_initialize.c`), and optional `board_early_initialize()`.
4. **`OSINIT_HARDWARE`**:
   - Sets up `stdin`, `stdout`, `stderr` on the IDLE task (`group_setupidlefiles()`), which all child tasks inherit.
   - If `CONFIG_SMP=y`, starts secondary CPUs via `nx_smp_start()`.
5. **`OSINIT_OSREADY`**:
   - Calls `nx_bringup()` (`sched/init/nx_bringup.c`), which starts kernel worker threads (`kwork`), invokes `board_late_initialize()` (if configured), and spawns the initial user task (`CONFIG_INIT_ENTRYPOINT`, typically `nsh_main`).
6. **`OSINIT_IDLELOOP`**:
   - Unlocks the scheduler (`sched_unlock()`) and enters the infinite `up_idle()` loop on CPU0.

---

## 3. Synchronization & Context Rules

- **Interrupt Context (`up_interrupt_context()`)**:
  - Never call blocking APIs (`nxsem_wait`, `nxmutex_lock`, `kmm_malloc`, `usleep`) from an ISR.
  - Defer blocking or heavy work from an ISR to the High-Priority (`HPWORK`) or Low-Priority (`LPWORK`) kernel work queue using `work_queue()` (`include/nuttx/wqueue.h`).
- **Internal Kernel APIs vs. User POSIX APIs**:
  - Inside the kernel (`sched/`, `drivers/`, `fs/`, `net/`), use internal `nx*` functions (`nxsem_wait`, `nxmutex_lock`, `nxsched_get_tcb`, `file_open`, `psock_send`) which return negative `errno` values directly without modifying the user-space `errno` variable.
