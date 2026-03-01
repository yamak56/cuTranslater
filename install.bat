@echo off
chcp 65001 > nul
echo ========================================
echo  中国語字幕翻訳ツール セットアップ
echo ========================================
echo.

:: Python 3.11 の確認 (.python-version により自動選択)
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Python 3.11 が見つかりません。
    echo https://www.python.org/downloads/release/python-3119/
    echo からインストールしてください。
    pause
    exit /b 1
)

echo [1/3] pip をアップグレード中...
py -3.11 -m pip install --upgrade pip

echo.
echo [2/3] PaddlePaddle をインストール中...
py -3.11 -m pip install paddlepaddle

echo.
echo [3/3] その他のパッケージをインストール中...
py -3.11 -m pip install -r requirements.txt

echo.
echo ========================================
echo  セットアップ完了！
echo  run.bat を実行してアプリを起動してください
echo ========================================
pause
