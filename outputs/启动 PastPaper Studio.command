#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_PYTHON="$SCRIPT_DIR/../backend/.venv/bin/python"
if [[ ! -x "$PROJECT_PYTHON" ]]; then
  print "缺少 Python 环境，请按照 README 完成安装。"
  read "?按回车关闭窗口…"
  exit 1
fi
"$PROJECT_PYTHON" "$SCRIPT_DIR/start_studio.py" --restart
if [ "$?" -ne 0 ]; then
  read "?按回车关闭窗口…"
fi
