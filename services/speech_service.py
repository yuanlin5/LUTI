"""
=============================================================================
 语音转文字服务
=============================================================================
 使用 Google 免费语音识别 API，支持中文普通话。
 需要安装依赖：pip install SpeechRecognition pyaudio
 如果 pyaudio 安装失败，可改用：pip install pipwin && pipwin install pyaudio

 后续可切换到百度/讯飞：将 recognize_google 替换为对应的 API 调用。
=============================================================================
"""

import threading

# 尝试导入语音识别库（如果未安装则静默跳过）
try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False


class SpeechService:
    """
    语音识别服务。
    录音在线程中异步执行，不影响界面响应。
    """

    def __init__(self):
        self.recognizer = None
        if HAS_SR:
            self.recognizer = sr.Recognizer()

    def is_available(self):
        """检查语音识别功能是否可用（依赖库是否已安装）"""
        return HAS_SR and self.recognizer is not None

    def recognize(self, callback, error_callback=None):
        """
        开始语音识别（异步执行）。

        参数：
          callback       — 识别成功后调用，参数为识别出的文字
          error_callback — 识别失败后调用，参数为错误描述字符串
        """
        if not self.is_available():
            if error_callback:
                error_callback("语音识别库未安装，请运行: pip install SpeechRecognition pyaudio")
            return

        def _run():
            """在后台线程中执行录音和识别"""
            try:
                # 打开麦克风录音（先做 0.5 秒环境噪音校准）
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=30)

                # 发送到 Google 语音识别（language="zh-CN" 表示中文普通话）
                text = self.recognizer.recognize_google(audio, language="zh-CN")
                callback(text)

            except sr.WaitTimeoutError:
                if error_callback:
                    error_callback("未检测到语音输入，请重试")
            except sr.UnknownValueError:
                if error_callback:
                    error_callback("无法识别语音内容，请说得更清晰一些")
            except sr.RequestError as e:
                if error_callback:
                    error_callback(f"语音识别服务连接失败，请检查网络: {e}")
            except Exception as e:
                if error_callback:
                    error_callback(f"语音识别出错: {e}")

        # 启动后台线程（daemon=True 表示程序退出时自动结束线程）
        t = threading.Thread(target=_run, daemon=True)
        t.start()
