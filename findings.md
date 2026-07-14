# 当前有效发现

## 实现链路

- `clean_manlifang_full.py` 负责清洗阶段的生成图片目录重置。
- `build_manlifang_delivery_package.py` 从当前批次 `structured` 数据和原图读取图片，按原始 SHA-256 去重，生成 `漫立方_全量数据/images` 中的压缩 JPEG 交付副本。
- 交付构建使用 `.building` 临时目录，完成后替换目标目录；遗留 `.building` 目录属于可疑过程性产物。
- 当前正式漫立方资产共 3128 个唯一公开商品和 5528 张规范化图片。
- `captures/.../cleaned/images` 含 8507 个文件，占 1.941 GiB；目录按商品编码分组，数量高于 5527 个 L0 图片文件，存在同图跨商品复制。
- `captures/.../raw/images_downloaded` 含 5527 个文件，占 1.400 GiB，是当前批次哈希原图目录。
- `漫立方_全量数据/images` 含 5528 个文件，占 0.903 GiB，是独立生成的当前 L3 规范化图片（含占位图）。
- 漫立方目录 4.333 GiB 中，`cleaned/images` 单项占约 1.941 GiB，是主要冗余候选。
- 清洗脚本通过 `os.link(source, target)` 优先创建 NTFS 硬链接，失败时才 `shutil.copy2`；因此 `cleaned/images` 的逻辑大小不能直接视为可释放物理空间。
- 交付构建只读取工作簿 `图片映射.local_file` 指向的 `batch_dir` 相对源文件，不读取 `cleaned/images` 作为图片源。
- 漫立方工具目录存在 12 个可再生 `.pyc`，约 0.34 MiB；测试 `.py` 均受 Git 跟踪，是当前实现测试，不属于可删除垃圾。
- 清洗工作簿 `图片映射` 共 8506 行，`local_file` 全部指向 `raw/...`，0 行引用 `cleaned/images` 作为源；8506 个逻辑图片状态全部为 `hardlink`，对应 5527 个唯一 SHA-256。
- 下载清单包含 8499 条成功下载关系，按 SHA-256 去重后为 5527 个唯一 L0 图片；关系行数不能与唯一图片数混用。
- `cleaned/images` 是清洗工作簿提供的逻辑路径层。删除几乎不释放图片物理空间，反而会造成工作簿逻辑路径失效，因此保留。
- 项目级可再生缓存候选：淘宝浏览器 Cache 271.37 MiB、Code Cache 31.64 MiB、GPU/Dawn 缓存 2.10 MiB；1688 浏览器 Cache 149.09 MiB、Code Cache 62.93 MiB、GPU/Dawn 缓存 6.10 MiB。
- `data-workflow/1688/_detail_debug` 含旧脚本 `--debug` 生成的 2 个文件，14.91 MiB；正式 1688 L0 证据位于 `runtime/runs/1688/.../l0`，不应混同。
- 登录 Profile 和 Cookie 必须保留；只清理其中可再生的 Cache/Code Cache/GPU 缓存目录。
- 当前没有使用工作区浏览器 Profile 的采集或浏览器进程，缓存目录无活动占用证据。
- 工作区源码区共有 6 个 `__pycache__` 目录、26 个 `.pyc`，合计约 624 KiB；根 `.pytest_cache` 约 8.3 KiB。
- `data-workflow/runtime/tmp/pytest_multi` 是 pytest 生成的临时运行树，含 19 个小文件及一个测试符号链接，不是正式 `runtime/runs` 资产。
- `_detail_debug`、浏览器 Profile、`__pycache__`、`.pytest_cache` 均在 `.gitignore` 或生成目录规则覆盖范围内；测试源码本身受 Git 跟踪并保留。
- 两套浏览器 Profile 中共识别 24 个顶层 Cache 类目录；只删除这些目录，不删除 Profile 根、Cookies、Local Storage、Session Storage 或其他登录态数据。

## 最终删除清单

- `data-workflow/1688/.browser-profile/**/<*Cache*>` 与 `data-workflow/taobao/.browser-profile/**/<*Cache*>`：浏览器可再生缓存。
- `data-workflow/1688/_detail_debug/`：旧脚本显式 `--debug` 生成物，不是正式 L0 运行目录。
- `data-workflow/runtime/tmp/`：pytest 临时运行树，不是 `runtime/runs/`。
- `.pytest_cache/`：pytest 可再生缓存。
- 工作区源码范围内 6 个 `__pycache__/`：Python 可再生字节码。

## 明确保留

- 漫立方当前正式批次全部 L0、清洗 XLSX、L3 交付及 `cleaned/images` 硬链接逻辑层。
- 1688/淘宝登录 Profile 中非缓存的登录态和配置。
- `runtime/runs/` 下正式采集证据。
- 所有受 Git 跟踪的测试源码与实现文件。

## 清理结果

- 已删除 33 个白名单目录、8393 个文件，候选逻辑大小 553.14 MiB。
- E 盘可用空间实测增加 565.32 MiB；差异来自文件系统分配单元和目录元数据。
- 删除后 33 个目标均不存在，无残留或部分失败。
- 已删除 `cleaned/images/_placeholder/MLF_no_image.png`：3127 字节，当前工作簿 0 引用，当前代码 0 引用；空 `_placeholder` 目录同步删除。

## 漫立方图片目录复核

- `raw/images_downloaded`：5527 个唯一 L0 原图，1.400 GiB，必须保留。
- `cleaned/images`：8506 个当前工作簿引用的逻辑图片路径，显示 1.941 GiB，但全部是指向 L0 的 NTFS 硬链接，图片内容没有再次独立分配。
- `漫立方_全量数据/images`：5528 个当前 L3 图片，实际独立占 924.79 MiB。
- L3 中 4415 张、832.96 MiB 与 L0 哈希完全相同，来源于交付脚本 `shutil.copy2`；1112 张、91.82 MiB 是为满足 500 KiB/1000 px 要求生成的规范化图片，另有 1 张占位图。
- E 盘为 NTFS，当前系统 `fsutil file` 不提供块克隆能力。把 4415 张相同文件改成硬链接可省约 832.96 MiB，但会让 L3 原地修改同时改变 L0，违反默认的 L0 不可变边界。

## 验证结果

- `python -m pytest data-workflow -q -p no:cacheprovider`：57 项通过。
- 3128 个商品且 `product_code` 唯一数为 3128。
- 8499 条成功下载关系对应 5527 个唯一 L0 图片；全量 SHA-256 校验 0 缺失、0 不匹配。
- 清洗工作簿 8506 条图片关系，源路径与逻辑路径均 0 缺失。
- 当前 L3 交付包含 5528 张图片、1 个 XLSX、14 个工作表。

## 数据保护边界

- 当前批次的 fresh structured JSONL、raw responses 和 hash-named originals 是后续处理的来源资产，必须保留。
- 当前正式批次为 `captures/manlifang_full_20260710_110814/`；原始响应、结构化 JSONL 和哈希原图属于 L0，不可因分类或交付副本存在而删除。
- `cleaned/漫立方_新全量清洗主数据_20260712.xlsx` 属于当前 L1-L2 主数据；`漫立方_全量数据/` 属于当前有效 L3 交付，默认保留。
- L0 原始资产不可变；清理重点是分类复制图片、旧交付、调试输出、测试临时文件、缓存和可重建副本。
- 来源指南明确：后续清洗不继承旧 CSV/XLSX 分类结果，只读取当前批次结构化 JSONL、原始响应和哈希原图。

## 待确认

- 浏览器 Profile 是否有进程占用；存在占用时不终止用户会话，跳过对应缓存。
- 项目级 `__pycache__`、pytest 缓存和 `runtime/tmp` 的完整清单与 Git 忽略状态。
- 删除前后实际目录大小、关键数据计数和测试结果。
