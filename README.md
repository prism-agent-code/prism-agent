<h1 align="center" style="font-size: 3em; margin-bottom: 0.2em;">Prism-agent</h1>
<p align="center">
  <img alt="Prism-agent logo" src="https://img.shields.io/badge/Prism--agent-Bug%20Fixing%20Framework-6A5ACD?style=for-the-badge" />
</p>

<p align="center">
  <em>A coarse-to-fine multi-solution bug-fixing framework</em>
</p>

<p align="center">
  🔍 Diverse Repair Strategies &nbsp;|&nbsp; 🌿 Heuristic Local Branching &nbsp;|&nbsp; 🤝 Multi-agent Collaboration
</p>

---

## Introduction

Prism is a coarse-to-fine multi-solution bug-fixing framework that explores diverse repair strategies, refines them through heuristic local branching, and synthesizes complementary solutions via multi-agent collaboration.

---

## Install

### Install from source
Latest features, recommended for development.

```bash
git clone https://github.com/prism-agent-code/prism-agent.git
cd prism-agent
conda env create -f environment.yml
```

---

## Quick Start

```bash
cd src/workflow
python workflow.py \
  --instance_id <instance_id> \
  --tjs_repo <tjs_repo> \
  --dataset <dataset> \
  --tjs_test_date <tjs_test_date>
```

---

## Parameter Description

This script accepts four required command-line arguments to locate the dataset, specify the trajectory storage path, define the test date, and select the specific instance to process.

### 1. `--dataset`

- **Type:** `str`
- **Required:** Yes

Specifies the directory where the dataset is stored.

By default, the script reads the following file from this directory:

```bash
test-swebench_verified.parquet
```

For example, if you pass:

```bash
--dataset /data/swebench
```

then the actual file path read by the script will be:

```bash
/data/swebench/test-swebench_verified.parquet
```

---

### 2. `--tjs_repo`

- **Type:** `str`
- **Required:** Yes

Specifies the storage path for trajectory results.

This argument is assigned to the variable `REPO`. Although the variable name is `REPO`, in this context it actually refers to the output directory or file path for trajectory data rather than the name of a code repository.

It is typically used for:

- Saving trajectory data generated during execution
- Recording intermediate results, execution logs, or reasoning traces
- Providing the trajectory file path for later analysis, reproduction, or debugging

---

### 3. `--tjs_test_date`

- **Type:** `str`
- **Required:** Yes

Specifies the test date.

This argument is assigned to the variable `TEST_DATE`, and is generally used to:

- Mark the date of the current test run
- Distinguish different batches of test results
- Serve as a time identifier in result folders, logs, or reports

Example:

```bash
--tjs_test_date 2026-03-25
```

---

### 4. `--instance_id`

- **Type:** `str`
- **Required:** Yes

Specifies the exact sample ID (`instance ID`) to process.

This argument is assigned to the variable `require_instance`, and is typically used to:

- Process only one specific sample
- Filter the target instance from the full dataset
- Debug, reproduce, or verify a single SWE-bench case

Example:

```bash
--instance_id astropy__astropy-14182
```

---


## Usage Example

```bash
python your_script.py \
  --dataset /data/swebench \
  --tjs_repo /path/to/trajectory \
  --tjs_test_date 2026-03-25 \
  --instance_id astropy__astropy-14182
```

---

## Before Running

Please make sure that:

1. The directory specified by `--dataset` exists
2. The file `test-swebench_verified.parquet` exists in that directory