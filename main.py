# -*- coding: utf-8 -*-
"""Git 常用操作可视化（PyQt5）：切换分支、拉取、提交、推送、创建分支。"""

import locale
import os
import subprocess
import sys
from typing import List, Optional, Tuple

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
)

import git_ui


def _decode_git_stream(raw: Optional[bytes]) -> str:
    """解码 Git 子进程输出。Windows 上 Git 可能按系统代码页（如 GBK）写管道，不能假定 UTF-8。"""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    pref = locale.getpreferredencoding(False)
    if pref:
        try:
            return raw.decode(pref)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace")


def run_git(repo: str, args: List[str]) -> Tuple[int, str, str]:
    """在 repo 下执行 git 子命令，返回 (returncode, stdout, stderr)。"""
    cmd = ["git", "-C", repo, "-c", "core.quotePath=false"] + args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
        )
        return proc.returncode, _decode_git_stream(proc.stdout), _decode_git_stream(proc.stderr)
    except FileNotFoundError:
        return 127, "", "未找到 git 可执行文件，请安装 Git 并加入 PATH。\n"
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时。\n"
    except OSError as e:
        return 1, "", f"执行失败: {e}\n"


def is_git_repo(path: str) -> bool:
    code, _, _ = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return code == 0


def list_merge_conflict_paths(repo: str) -> List[str]:
    """列出仍处于合并/拉取冲突中、未解决（unmerged）的文件路径。"""
    code, out, _ = run_git(repo, ["diff", "--name-only", "--diff-filter=U"])
    if code != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


class GitTaskWorker(QObject):
    finished = pyqtSignal(int, str, str)  # code, out, err

    def __init__(self, repo: str, git_args: List[str]):
        super().__init__()
        self._repo = repo
        self._args = git_args

    def run(self) -> None:
        code, out, err = run_git(self._repo, self._args)
        self.finished.emit(code, out, err)


class MyMainForm(QMainWindow, git_ui.Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.verticalLayout_root.setStretchFactor(self.output, 1)
        self.verticalLayout_root.setStretchFactor(self.text_log, 1)
        self.label_output.setText("git status / 命令输出（行首 ?? 表示未跟踪文件，不是乱码）:")
        self.label_output.setToolTip(
            "短状态对照：?? 未跟踪 | M 修改 | A 新增 | D 删除 | R 重命名；"
            "「?? 备份/」表示文件夹「备份」尚未被 Git 跟踪。"
        )

        self._repo = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
        self.path_edit.setText(self._repo)
        self._thread: Optional[QThread] = None
        self._worker: Optional[GitTaskWorker] = None

        self._busy_buttons: List[QPushButton] = [
            self.btn_refresh,
            self.btn_switch,
            self.btn_create,
            self.btn_pull,
            self.btn_push,
            self.btn_commit,
        ]

        self.btn_browse.clicked.connect(self._pick_repo)
        self.btn_refresh.clicked.connect(self.refresh_branches)
        self.btn_switch.clicked.connect(self.switch_branch)
        self.btn_create.clicked.connect(self.create_branch)
        self.btn_pull.clicked.connect(self.do_pull)
        self.btn_push.clicked.connect(self.do_push)
        self.btn_commit.clicked.connect(self.do_commit)
        self.btn_refresh_head_log.clicked.connect(self.refresh_head_and_log)

        self.refresh_branches()
        self._append_status()
        self.refresh_head_and_log()

    def _repo_path(self) -> str:
        return self.path_edit.text().strip() or self._repo

    def refresh_head_and_log(self) -> None:
        """刷新当前 HEAD 信息与最近提交列表。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            self.text_head.setPlainText("")
            self.text_log.setPlainText("")
            return

        bcode, branch_out, _ = run_git(repo, ["branch", "--show-current"])
        br = branch_out.strip()
        if bcode == 0 and br:
            branch_line = br
        else:
            branch_line = "（分离 HEAD 或无当前分支名）"

        # 当前提交：短哈希、说明、作者、时间、完整哈希
        pretty = "%h · %s%n作者: %an <%ae>%n时间: %ci%n完整哈希: %H"
        code, out, err = run_git(repo, ["log", "-1", f"--pretty=format:{pretty}"])
        if code != 0:
            msg = f"分支: {branch_line}\n\n（尚无提交或无法读取 HEAD）"
            if err.strip():
                msg += "\n" + err.strip()
            self.text_head.setPlainText(msg)
        else:
            self.text_head.setPlainText(f"分支: {branch_line}\n\n{out.strip()}")

        code2, out2, err2 = run_git(repo, ["log", "-n", "30", "--oneline", "--decorate"])
        if code2 != 0:
            self.text_log.setPlainText(
                err2.strip() if err2.strip() else "（暂无提交记录）"
            )
        else:
            self.text_log.setPlainText(out2.strip())

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

    def _report_merge_conflicts(self, popup: bool = False) -> None:
        """检测未合并文件；在输出区列出，必要时弹窗（用于拉取后出现冲突）。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            return
        paths = list_merge_conflict_paths(repo)
        if not paths:
            return
        n = len(paths)
        lines = "\n".join(paths)
        self.output.append(
            f"*** 合并冲突：以下 {n} 个文件仍处于未合并状态，请手动编辑解决后再 git add ***\n{lines}"
        )
        if popup:
            QMessageBox.warning(
                self,
                "合并 / 拉取冲突",
                f"检测到未解决的合并冲突（共 {n} 个文件）。\n\n"
                "请在编辑器中打开下列文件，查找并处理 <<<<<<< / ======= / >>>>>>> 标记后，"
                "再暂存并提交。\n\n"
                f"{lines}",
            )

    def _append_status(self, conflict_popup: bool = False) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            self.output.append("当前目录不是 Git 仓库，请选择有效仓库。")
            return
        code, out, err = run_git(repo, ["status", "-sb"])
        self._append_log("git status -sb", code, out, err)
        self._report_merge_conflicts(popup=conflict_popup)

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
        self.refresh_head_and_log()

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
            self.refresh_head_and_log()

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
            self.refresh_head_and_log()

    def do_commit(self) -> None:
        repo = self._repo_path()
        msg = self.commit_msg.text().strip()
        if not msg:
            QMessageBox.information(self, "提示", "请填写提交说明。")
            return
        paths = list_merge_conflict_paths(repo)
        if paths:
            QMessageBox.warning(
                self,
                "无法提交",
                "当前仍有未解决的合并冲突，请先解决冲突并暂存后再提交。\n\n"
                + "\n".join(paths),
            )
            self._report_merge_conflicts(popup=False)
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
        self.refresh_head_and_log()

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

        is_pull = bool(git_args and git_args[0] == "pull")

        def on_done(code: int, out: str, err: str) -> None:
            self._append_log(" ".join(["git"] + git_args), code, out, err)
            self._set_busy(False)
            if code == 0 and git_args and git_args[0] in ("pull", "push", "fetch"):
                self.refresh_branches()
            # 拉取无论成功与否都可能留下冲突（例如 fetch 成功 merge 失败）
            self._append_status(conflict_popup=is_pull)
            self.refresh_head_and_log()

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
    w = MyMainForm()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
