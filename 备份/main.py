# -*- coding: utf-8 -*-
"""Git 常用操作可视化（PyQt5）：切换分支、拉取、提交、推送、创建分支。"""

import os
import subprocess
import sys
from typing import List, Optional, Tuple

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def run_git(repo: str, args: List[str]) -> Tuple[int, str, str]:
    """在 repo 下执行 git 子命令，返回 (returncode, stdout, stderr)。"""
    cmd = ["git", "-C", repo] + args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "未找到 git 可执行文件，请安装 Git 并加入 PATH。\n"
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时。\n"
    except OSError as e:
        return 1, "", f"执行失败: {e}\n"


def is_git_repo(path: str) -> bool:
    code, _, _ = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return code == 0


class GitTaskWorker(QObject):
    finished = pyqtSignal(int, str, str)  # code, out, err

    def __init__(self, repo: str, git_args: List[str]):
        super().__init__()
        self._repo = repo
        self._args = git_args

    def run(self) -> None:
        code, out, err = run_git(self._repo, self._args)
        self.finished.emit(code, out, err)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Git 可视化操作")
        self.resize(720, 560)

        self._repo = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
        self._thread: Optional[QThread] = None
        self._worker: Optional[GitTaskWorker] = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 仓库路径
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(self._repo)
        self.path_edit.setReadOnly(True)
        btn_browse = QPushButton("选择仓库…")
        btn_browse.clicked.connect(self._pick_repo)
        path_row.addWidget(QLabel("仓库目录:"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_browse)
        root.addLayout(path_row)

        # 分支
        branch_box = QGroupBox("分支")
        bf = QHBoxLayout(branch_box)
        self.branch_combo = QComboBox()
        self.branch_combo.setMinimumWidth(220)
        btn_refresh = QPushButton("刷新分支")
        btn_refresh.clicked.connect(self.refresh_branches)
        btn_switch = QPushButton("切换到所选分支")
        btn_switch.clicked.connect(self.switch_branch)
        bf.addWidget(QLabel("本地分支:"))
        bf.addWidget(self.branch_combo, 1)
        bf.addWidget(btn_refresh)
        bf.addWidget(btn_switch)
        root.addWidget(branch_box)

        # 新建分支
        new_box = QGroupBox("新建分支")
        nf = QHBoxLayout(new_box)
        self.new_branch_edit = QLineEdit()
        self.new_branch_edit.setPlaceholderText("新分支名称")
        btn_create = QPushButton("创建并切换")
        btn_create.clicked.connect(self.create_branch)
        nf.addWidget(QLabel("名称:"))
        nf.addWidget(self.new_branch_edit, 1)
        nf.addWidget(btn_create)
        root.addWidget(new_box)

        # 远程操作
        remote_box = QGroupBox("远程")
        rf = QHBoxLayout(remote_box)
        btn_pull = QPushButton("拉取 (git pull)")
        btn_pull.clicked.connect(self.do_pull)
        btn_push = QPushButton("推送 (git push)")
        btn_push.clicked.connect(self.do_push)
        rf.addWidget(btn_pull)
        rf.addWidget(btn_push)
        rf.addStretch()
        root.addWidget(remote_box)

        # 提交
        commit_box = QGroupBox("提交")
        cf = QVBoxLayout(commit_box)
        form = QFormLayout()
        self.commit_msg = QLineEdit()
        self.commit_msg.setPlaceholderText("提交说明（将暂存所有变更后提交）")
        form.addRow("说明:", self.commit_msg)
        cf.addLayout(form)
        btn_commit = QPushButton("暂存全部并提交")
        btn_commit.clicked.connect(self.do_commit)
        cf.addWidget(btn_commit)
        root.addWidget(commit_box)

        # 状态与日志
        root.addWidget(QLabel("git status / 命令输出:"))
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(200)
        root.addWidget(self.output, 1)

        self._busy_buttons: List[QPushButton] = [
            btn_refresh,
            btn_switch,
            btn_create,
            btn_pull,
            btn_push,
            btn_commit,
        ]

        self.refresh_branches()
        self._append_status()

    def _repo_path(self) -> str:
        return self.path_edit.text().strip() or self._repo

    def _append_log(self, title: str, code: int, out: str, err: str) -> None:
        block = f"=== {title} (exit {code}) ===\n"
        if out.strip():
            block += out
            if not out.endswith("\n"):
                block += "\n"
        if err.strip():
            block += err
            if not err.endswith("\n"):
                block += "\n"
        self.output.append(block.rstrip("\n"))

    def _append_status(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            self.output.append("当前目录不是 Git 仓库，请选择有效仓库。")
            return
        code, out, err = run_git(repo, ["status", "-sb"])
        self._append_log("git status -sb", code, out, err)

    def _pick_repo(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择 Git 仓库根目录", self._repo_path())
        if not d:
            return
        if not is_git_repo(d):
            QMessageBox.warning(self, "提示", "所选目录不是 Git 工作区。")
            return
        self.path_edit.setText(os.path.abspath(d))
        self.refresh_branches()
        self.output.clear()
        self._append_status()

    def refresh_branches(self) -> None:
        repo = self._repo_path()
        self.branch_combo.clear()
        if not is_git_repo(repo):
            self.output.append("无效仓库，无法列出分支。")
            return
        code, out, err = run_git(repo, ["branch", "--list", "--format=%(refname:short)"])
        if code != 0:
            self._append_log("git branch", code, out, err)
            return
        names = [ln.strip() for ln in out.splitlines() if ln.strip()]
        self.branch_combo.addItems(names)
        # 当前分支标星
        ccode, cout, _ = run_git(repo, ["branch", "--show-current"])
        if ccode == 0:
            cur = cout.strip()
            idx = self.branch_combo.findText(cur)
            if idx >= 0:
                self.branch_combo.setCurrentIndex(idx)

    def switch_branch(self) -> None:
        repo = self._repo_path()
        name = self.branch_combo.currentText().strip()
        if not name:
            QMessageBox.information(self, "提示", "请先选择分支。")
            return
        code, out, err = run_git(repo, ["checkout", name])
        self._append_log(f"git checkout {name}", code, out, err)
        if code == 0:
            self.refresh_branches()
            self._append_status()

    def create_branch(self) -> None:
        repo = self._repo_path()
        name = self.new_branch_edit.text().strip()
        if not name:
            QMessageBox.information(self, "提示", "请输入新分支名称。")
            return
        code, out, err = run_git(repo, ["checkout", "-b", name])
        self._append_log(f"git checkout -b {name}", code, out, err)
        if code == 0:
            self.new_branch_edit.clear()
            self.refresh_branches()
            self._append_status()

    def do_commit(self) -> None:
        repo = self._repo_path()
        msg = self.commit_msg.text().strip()
        if not msg:
            QMessageBox.information(self, "提示", "请填写提交说明。")
            return
        code, out, err = run_git(repo, ["add", "-A"])
        self._append_log("git add -A", code, out, err)
        if code != 0:
            return
        code2, out2, err2 = run_git(repo, ["commit", "-m", msg])
        self._append_log(f'git commit -m "{msg}"', code2, out2, err2)
        if code2 == 0:
            self.commit_msg.clear()
        self._append_status()

    def _set_busy(self, busy: bool) -> None:
        for b in self._busy_buttons:
            b.setEnabled(not busy)

    def _run_async(self, git_args: List[str]) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先选择有效 Git 仓库。")
            return
        if self._thread is not None:
            QMessageBox.information(self, "请稍候", "上一项任务仍在执行。")
            return

        self._set_busy(True)
        self._thread = QThread()
        self._worker = GitTaskWorker(repo, git_args)
        self._worker.moveToThread(self._thread)

        def on_done(code: int, out: str, err: str) -> None:
            self._append_log(" ".join(["git"] + git_args), code, out, err)
            self._set_busy(False)
            if code == 0 and git_args and git_args[0] in ("pull", "push", "fetch"):
                self.refresh_branches()
            self._append_status()

        def on_thread_finished() -> None:
            self._thread = None
            self._worker = None

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(on_done)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(on_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def do_pull(self) -> None:
        self._run_async(["pull"])

    def do_push(self) -> None:
        self._run_async(["push"])


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
