# -*- coding: utf-8 -*-
"""Git 常用操作可视化（PyQt5）：克隆/初始化、分支、checkout、远端与身份、fetch/pull/push、提交。"""

import locale
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple, Union

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
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


def run_git_raw(args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """执行 git 子命令（不使用 -C），用于 clone 等。"""
    cmd = ["git", "-c", "core.quotePath=false"] + args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
            cwd=cwd,
        )
        return proc.returncode, _decode_git_stream(proc.stdout), _decode_git_stream(proc.stderr)
    except FileNotFoundError:
        return 127, "", "未找到 git 可执行文件，请安装 Git 并加入 PATH。\n"
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时。\n"
    except OSError as e:
        return 1, "", f"执行失败: {e}\n"


def default_clone_folder(url: str) -> str:
    """从 clone URL 推测默认文件夹名。"""
    u = url.strip()
    if not u:
        return ""
    u = re.split(r"[/:@]", u.replace("\\", "/"))[-1]
    if u.endswith(".git"):
        u = u[:-4]
    return u or "repo"


def list_git_remotes(repo: str) -> List[str]:
    code, out, _ = run_git(repo, ["remote"])
    if code != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def parse_remote_add_paste(raw: str) -> Optional[Tuple[str, str]]:
    """解析粘贴内容：整行「git remote add <name> <url>」，或可省略开头的 git remote add。"""
    prefix = "git remote add"
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith(prefix):
            s = s[len(prefix):].strip()
        parts = s.split(None, 1)
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1].strip().strip('"\'')
        if name and url:
            return name, url
    return None


def default_startup_directory() -> str:
    """源码运行时默认脚本所在目录；打包成 exe 后 __file__ 在临时 _MEI* 目录，改用启动时工作目录。"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(os.getcwd())
    return os.path.abspath(os.path.dirname(os.path.abspath(__file__)))


def is_git_repo(path: str) -> bool:
    code, _, _ = run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return code == 0


def list_merge_conflict_paths(repo: str) -> List[str]:
    """列出仍处于合并/拉取冲突中、未解决（unmerged）的文件路径。"""
    code, out, _ = run_git(repo, ["diff", "--name-only", "--diff-filter=U"])
    if code != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def list_remote_branch_short_names(repo: str) -> List[str]:
    """列出远程分支短名（如 origin/main），排除 HEAD 符号链接行。"""
    code, out, _ = run_git(repo, ["branch", "-r"])
    if code != 0:
        return []
    names: List[str] = []
    for ln in out.splitlines():
        s = ln.strip().lstrip("*").strip()
        if not s or "->" in s:
            continue
        names.append(s)
    return sorted(set(names))


def is_remote_tracking_branch(repo: str, ref_short: str) -> bool:
    """ref_short 是否为 refs/remotes/<ref_short>（例如 origin/main）。"""
    code, _, _ = run_git(repo, ["rev-parse", "--verify", f"refs/remotes/{ref_short}"])
    return code == 0


def local_branch_exists(repo: str, name: str) -> bool:
    code, _, _ = run_git(repo, ["rev-parse", "--verify", f"refs/heads/{name}"])
    return code == 0


def format_upstream_summary(repo: str) -> str:
    """当前分支的上游与相对领先/落后提交数（若无上游则给出说明）。"""
    uc, upstream_ref, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "@{upstream}"])
    if uc != 0:
        return "上游跟踪: （未设置；首次推送可用 git push -u）"
    up = upstream_ref.strip()
    line = f"上游跟踪: {up}"
    rc, cnt, _ = run_git(repo, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if rc != 0:
        return line
    parts = cnt.strip().split()
    if len(parts) >= 2:
        ahead, behind = parts[0], parts[1]
        line += f"\n相对上游: 领先 {ahead} · 落后 {behind}（仅本地 / 仅远端）"
    return line


class GitTaskWorker(QObject):
    finished = pyqtSignal(int, str, str)  # code, out, err

    def __init__(self, repo: str, git_args: List[str]):
        super().__init__()
        self._repo = repo
        self._args = git_args

    def run(self) -> None:
        code, out, err = run_git(self._repo, self._args)
        self.finished.emit(code, out, err)


class GitRawTaskWorker(QObject):
    """用于不绑定具体仓库路径的 git 调用（如 clone）。"""

    finished = pyqtSignal(int, str, str)

    def __init__(self, argv: List[str], cwd: Optional[str] = None):
        super().__init__()
        self._argv = argv
        self._cwd = cwd

    def run(self) -> None:
        code, out, err = run_git_raw(self._argv, self._cwd)
        self.finished.emit(code, out, err)


class CloneRepoDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], default_parent: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("克隆仓库")
        root = QVBoxLayout(self)
        self._url = QLineEdit()
        self._parent = QLineEdit(default_parent)
        self._folder = QLineEdit()
        form = QFormLayout()
        form.addRow("仓库 URL:", self._url)
        row = QHBoxLayout()
        row.addWidget(self._parent, 1)
        btn_pick = QPushButton("浏览…")
        btn_pick.clicked.connect(self._browse_parent)
        row.addWidget(btn_pick)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow("保存到父目录:", wrap)
        form.addRow("文件夹名:", self._folder)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._url.textChanged.connect(self._maybe_autofill_folder)

    def _browse_parent(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择父目录", self._parent.text().strip() or os.path.expanduser("~"))
        if d:
            self._parent.setText(os.path.abspath(d))

    def _maybe_autofill_folder(self, _: str) -> None:
        if self._folder.text().strip():
            return
        u = self._url.text().strip()
        if u:
            self._folder.setText(default_clone_folder(u))

    def _try_accept(self) -> None:
        url = self._url.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请填写仓库 URL。")
            return
        pd = self._parent.text().strip()
        if not pd or not os.path.isdir(pd):
            QMessageBox.warning(self, "提示", "请选择有效的父目录。")
            return
        fold = self._folder.text().strip() or default_clone_folder(url)
        if not fold or fold in (".", "..") or "/" in fold or "\\" in fold:
            QMessageBox.warning(self, "提示", "文件夹名无效（应为单层目录名）。")
            return
        dest = os.path.join(os.path.abspath(pd), fold)
        if os.path.exists(dest):
            if not os.path.isdir(dest):
                QMessageBox.warning(self, "提示", "目标路径已存在且不是目录。")
                return
            if os.listdir(dest):
                QMessageBox.warning(self, "提示", "目标目录已存在且非空。")
                return
        self.accept()

    def clone_url(self) -> str:
        return self._url.text().strip()

    def clone_parent_dir(self) -> str:
        return os.path.abspath(self._parent.text().strip())

    def clone_folder_name(self) -> str:
        url = self._url.text().strip()
        return self._folder.text().strip() or default_clone_folder(url)


class MyMainForm(QMainWindow, git_ui.Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.verticalLayout_root.setStretchFactor(self.main_tabs, 1)
        self.verticalLayout_tab2.setStretchFactor(self.group_head_log, 1)
        self.verticalLayout_tab2.setStretchFactor(self.output, 1)
        self.verticalLayout_head_log.setStretchFactor(self.text_log, 1)
        self.label_output.setText("git status / 命令输出（行首 ?? 表示未跟踪文件，不是乱码）:")
        self.label_output.setToolTip(
            "短状态对照：?? 未跟踪 | M 修改 | A 新增 | D 删除 | R 重命名；"
            "「?? 备份/」表示文件夹「备份」尚未被 Git 跟踪。"
        )
        self.label_branch.setToolTip(
            "下拉框上方为本地分支，其后为远程分支（origin/…）。"
            "选择远程分支时：若已有同名本地分支则直接切换；否则创建本地分支并跟踪该远程分支。"
        )
        self.group_history.setToolTip("等价于在仓库目录执行 git checkout <填写内容>。")

        self._repo = default_startup_directory()
        self.path_edit.setText(self._repo)
        self._thread: Optional[QThread] = None
        self._worker: Optional[Union[GitTaskWorker, GitRawTaskWorker]] = None

        self._busy_buttons: List[QPushButton] = [
            self.btn_clone,
            self.btn_refresh,
            self.btn_switch,
            self.btn_create,
            self.btn_history_checkout,
            self.btn_fetch,
            self.btn_pull,
            self.btn_push,
            self.btn_stage_all,
            self.btn_commit_all,
            self.btn_restore_staged,
            self.btn_reset_soft_parent,
        ]

        id_tip = "显示顺序：先读本仓库 --local，若无则读全局 --global；保存仅写入本仓库。"
        self.edit_git_user_name.setToolTip(id_tip)
        self.edit_git_user_email.setToolTip(id_tip)
        self.btn_restore_staged.setToolTip("git restore --staged .：取消暂存，工作区文件内容不变。")
        self.btn_reset_soft_parent.setToolTip("git reset --soft HEAD^：去掉最近一次提交，改动仍在暂存区。")

        self.btn_browse.clicked.connect(self._pick_repo)
        self.btn_clone.clicked.connect(self.do_clone)
        self.btn_init.clicked.connect(self.do_init_repo)
        self.btn_refresh.clicked.connect(self.refresh_branches)
        self.btn_switch.clicked.connect(self.switch_branch)
        self.btn_create.clicked.connect(self.create_branch)
        self.btn_history_checkout.clicked.connect(self.do_checkout_ref)
        self.btn_fetch.clicked.connect(self.do_fetch)
        self.btn_pull.clicked.connect(self.do_pull)
        self.btn_push.clicked.connect(self.do_push)
        self.btn_stage_all.clicked.connect(self.do_stage_all)
        self.btn_commit_all.clicked.connect(self.do_commit_all)
        self.btn_restore_staged.clicked.connect(self.do_restore_staged)
        self.btn_reset_soft_parent.clicked.connect(self.do_reset_soft_parent)
        self.btn_refresh_head_log.clicked.connect(self.refresh_head_and_log)
        self.btn_refresh_remote_list.clicked.connect(self.refresh_remote_display)
        self.btn_remote_add.clicked.connect(self.remote_add)
        self.btn_remote_set_url.clicked.connect(self.remote_set_url)
        self.btn_save_identity.clicked.connect(self.save_identity)

        self.refresh_branches()
        self._append_status()
        self.refresh_head_and_log()
        self._update_repo_auxiliary_ui()

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

        upstream_block = format_upstream_summary(repo)

        # 当前提交：短哈希、说明、作者、时间、完整哈希
        pretty = "%h · %s%n作者: %an <%ae>%n时间: %ci%n完整哈希: %H"
        code, out, err = run_git(repo, ["log", "-1", f"--pretty=format:{pretty}"])
        if code != 0:
            msg = f"分支: {branch_line}\n{upstream_block}\n\n（尚无提交或无法读取 HEAD）"
            if err.strip():
                msg += "\n" + err.strip()
            self.text_head.setPlainText(msg)
        else:
            self.text_head.setPlainText(f"分支: {branch_line}\n{upstream_block}\n\n{out.strip()}")

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
        self._update_repo_auxiliary_ui()

    def _update_repo_auxiliary_ui(self) -> None:
        repo = self._repo_path()
        ok = is_git_repo(repo)
        for w in (
            self.btn_refresh_remote_list,
            self.btn_remote_add,
            self.btn_remote_set_url,
            self.btn_save_identity,
            self.edit_git_user_name,
            self.edit_git_user_email,
        ):
            w.setEnabled(ok)
        if ok:
            self.refresh_remote_display()
            self.load_identity_fields()
        else:
            self.text_remote_urls.clear()
            self.edit_git_user_name.clear()
            self.edit_git_user_email.clear()

    def refresh_remote_display(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            self.text_remote_urls.clear()
            return
        code, out, err = run_git(repo, ["remote", "-v"])
        if code != 0:
            self.text_remote_urls.setPlainText(err.strip() or "（无法读取 git remote -v）")
            return
        text = out.strip()
        self.text_remote_urls.setPlainText(text if text else "（尚无远端，可点击「添加远端」）")

    def load_identity_fields(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            return
        for key, edit in (
            ("user.name", self.edit_git_user_name),
            ("user.email", self.edit_git_user_email),
        ):
            c, out, _ = run_git(repo, ["config", "--local", "--get", key])
            if c != 0:
                c, out, _ = run_git(repo, ["config", "--global", "--get", key])
            edit.setText(out.strip() if c == 0 else "")

    def save_identity(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
        name = self.edit_git_user_name.text().strip()
        email = self.edit_git_user_email.text().strip()
        if not name or not email:
            QMessageBox.warning(self, "提示", "请填写 user.name 与 user.email。")
            return
        c1, _, e1 = run_git(repo, ["config", "--local", "user.name", name])
        c2, _, e2 = run_git(repo, ["config", "--local", "user.email", email])
        self._append_log("git config --local user.name …", c1, "", e1)
        self._append_log("git config --local user.email …", c2, "", e2)
        if c1 == 0 and c2 == 0:
            QMessageBox.information(self, "完成", "已保存到本仓库配置（.git/config）。")

    def remote_add(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            return
        hint = (
            "粘贴一行即可，例如：\n"
            "git remote add origin https://github.com/用户名/仓库名.git\n\n"
            "也可省略前缀，只写：origin https://……"
        )
        text, ok = QInputDialog.getMultiLineText(self, "添加远端", hint, "")
        if not ok:
            return
        parsed = parse_remote_add_paste(text)
        if not parsed:
            QMessageBox.warning(
                self,
                "无法解析",
                "请粘贴形如：\n"
                "git remote add origin https://github.com/用户名/仓库.git\n"
                "（远端名与 URL 之间用空格分开）",
            )
            return
        nm, url = parsed
        code, out, err = run_git(repo, ["remote", "add", nm, url])
        self._append_log(f"git remote add {nm} {url}", code, out, err)
        if code == 0:
            self.refresh_remote_display()

    def remote_set_url(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            return
        remotes = list_git_remotes(repo)
        if not remotes:
            QMessageBox.information(self, "提示", "当前没有已配置的远端。")
            return
        nm, ok = QInputDialog.getItem(self, "修改 fetch URL", "选择远端:", remotes, 0, False)
        if not ok:
            return
        url, ok2 = QInputDialog.getText(self, "修改 fetch URL", "新的 fetch URL:")
        if not ok2 or not url.strip():
            return
        url = url.strip()
        code, out, err = run_git(repo, ["remote", "set-url", nm, url])
        self._append_log(f"git remote set-url {nm} …", code, out, err)
        if code == 0:
            self.refresh_remote_display()

    def do_clone(self) -> None:
        # 父目录默认：系统当前工作目录（由启动方式决定，如资源管理器所在目录、终端 cd 位置）
        parent_default = os.path.abspath(os.getcwd())
        dlg = CloneRepoDialog(self, parent_default)
        if dlg.exec_() != QDialog.Accepted:
            return
        url = dlg.clone_url()
        dest = os.path.join(dlg.clone_parent_dir(), dlg.clone_folder_name())
        self._run_clone_async(url, dest)

    def do_init_repo(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择要初始化为 Git 仓库的目录", self._repo_path())
        if not d:
            return
        d = os.path.abspath(d)
        if is_git_repo(d):
            QMessageBox.warning(self, "提示", "该目录已是 Git 工作区。")
            return
        code, out, err = run_git(d, ["init"])
        self._append_log(f"git init ({d})", code, out, err)
        if code != 0:
            return
        self.path_edit.setText(d)
        self.output.clear()
        self.refresh_branches()
        self._append_status()
        self.refresh_head_and_log()
        self._update_repo_auxiliary_ui()

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
        remotes = list_remote_branch_short_names(repo)
        self.branch_combo.addItems(names + remotes)
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
        if is_remote_tracking_branch(repo, name):
            _, rest = name.split("/", 1)
            if local_branch_exists(repo, rest):
                args: List[str] = ["checkout", rest]
                title = f"git checkout {rest}"
            else:
                args = ["checkout", "-b", rest, "--track", name]
                title = f"git checkout -b {rest} --track {name}"
        else:
            args = ["checkout", name]
            title = f"git checkout {name}"
        code, out, err = run_git(repo, args)
        self._append_log(title, code, out, err)
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

    def do_checkout_ref(self) -> None:
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
        ref = self.history_ref_edit.text().strip()
        if not ref:
            QMessageBox.information(self, "提示", "请填写提交哈希或分支名。")
            return
        code, out, err = run_git(repo, ["checkout", ref])
        self._append_log(f"git checkout {ref}", code, out, err)
        if code == 0:
            self.refresh_branches()
            self._append_status()
            self.refresh_head_and_log()

    def do_stage_all(self) -> None:
        """git add .：暂存当前目录下变更（新文件、修改），详见 Git 文档。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
        code, out, err = run_git(repo, ["add", "."])
        self._append_log("git add .", code, out, err)
        if code == 0:
            self._append_status()
            self.refresh_head_and_log()

    def do_commit_all(self) -> None:
        """git commit -m：将已暂存的变更提交（需先暂存，或用「暂存全部」）。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
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
        code, out, err = run_git(repo, ["commit", "-m", msg])
        self._append_log(f'git commit -m "{msg}"', code, out, err)
        if code == 0:
            self.commit_msg.clear()
        self._append_status()
        self.refresh_head_and_log()

    def do_restore_staged(self) -> None:
        """git restore --staged .：仅撤销暂存，工作区保留修改。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
        code, out, err = run_git(repo, ["restore", "--staged", "."])
        self._append_log("git restore --staged .", code, out, err)
        if code == 0:
            self._append_status()
            self.refresh_head_and_log()

    def do_reset_soft_parent(self) -> None:
        """git reset --soft HEAD^：撤销上一提交，改动保留在暂存区。"""
        repo = self._repo_path()
        if not is_git_repo(repo):
            QMessageBox.warning(self, "提示", "请先打开有效 Git 仓库。")
            return
        reply = QMessageBox.question(
            self,
            "确认",
            "将执行 git reset --soft HEAD^：撤销最近一次提交，改动仍保留在暂存区。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        code, out, err = run_git(repo, ["reset", "--soft", "HEAD^"])
        self._append_log("git reset --soft HEAD^", code, out, err)
        if code == 0:
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

    def do_fetch(self) -> None:
        self._run_async(["fetch", "--prune"])

    def _run_clone_async(self, url: str, dest: str) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "请稍候", "上一项任务仍在执行。")
            return

        self._set_busy(True)
        self._thread = QThread()
        self._worker = GitRawTaskWorker(["clone", url, dest])
        self._worker.moveToThread(self._thread)

        def on_done(code: int, out: str, err: str) -> None:
            self._append_log(f"git clone → {dest}", code, out, err)
            self._set_busy(False)
            if code == 0:
                self.path_edit.setText(os.path.abspath(dest))
                self.output.clear()
                self.refresh_branches()
                self._append_status()
                self.refresh_head_and_log()
                self._update_repo_auxiliary_ui()

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


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MyMainForm()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
