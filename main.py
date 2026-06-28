

import os
import sys
import time
import json
import datetime
import threading
import queue
import webbrowser
import logging
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.animation import Animation
from kivy.properties import StringProperty, ColorProperty, NumericProperty
from kivy.utils import platform

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("VoiceAssistant")

# Import SpeechRecognition library
import speech_recognition as sr

# ==========================================
# 1. Native Android Audio Capture via Pyjnius
# ==========================================
class AndroidMicrophone(sr.AudioSource):
    """
    A custom AudioSource wrapper for Python SpeechRecognition that captures 
    raw PCM audio from the native Android microphone using Pyjnius.
    This eliminates the need for PyAudio on Android.
    """
    def __init__(self, sample_rate=16000, chunk_size=1024):
        self.SAMPLE_RATE = sample_rate
        self.SAMPLE_WIDTH = 2  # 16-bit PCM = 2 bytes per sample
        self.CHUNK = chunk_size
        self.queue = queue.Queue()
        self.recording = False
        self.thread = None
        self.audio_record = None
        self.j_buffer = None
        
    def __enter__(self):
        logger.info("Initializing Android AudioRecord source via JNI")
        if platform != 'android':
            raise RuntimeError("AndroidMicrophone is only supported on Android")
            
        try:
            from jnius import autoclass
            AudioRecord = autoclass('android.media.AudioRecord')
            AudioSource = autoclass('android.media.MediaRecorder$AudioSource')
            AudioFormat = autoclass('android.media.AudioFormat')
            Byte = autoclass('java.lang.Byte')
            Array = autoclass('java.lang.reflect.Array')
            
            # Configure native AudioRecord parameters
            channel_config = AudioFormat.CHANNEL_IN_MONO
            audio_format = AudioFormat.ENCODING_PCM_16BIT
            
            # Calculate minimum buffer size required by hardware
            min_buffer_size = AudioRecord.getMinBufferSize(
                self.SAMPLE_RATE, channel_config, audio_format
            )
            
            # Create the Java AudioRecord instance
            self.audio_record = AudioRecord(
                AudioSource.MIC,
                self.SAMPLE_RATE,
                channel_config,
                audio_format,
                max(min_buffer_size, self.CHUNK * 2)
            )
            
            # Create a Java primitive byte array to store chunk data
            self.j_buffer = Array.newInstance(Byte.TYPE, self.CHUNK * 2)
            
            # Start recording and spawn reader thread
            self.audio_record.startRecording()
            self.recording = True
            
            self.thread = threading.Thread(target=self._record_loop, name="AndroidMicReader")
            self.thread.daemon = True
            self.thread.start()
            logger.info("Android AudioRecord successfully started")
        except Exception as e:
            logger.error(f"Failed to initialize AndroidMicrophone: {e}", exc_info=True)
            self.__exit__(None, None, None)
            raise e
            
        return self

    def _record_loop(self):
        """Background thread reading from native AudioRecord buffer to avoid JNI blockage."""
        while self.recording:
            try:
                # Read PCM bytes from native record object
                bytes_read = self.audio_record.read(self.j_buffer, 0, len(self.j_buffer))
                if bytes_read > 0:
                    # Convert Java signed byte[] array to unsigned Python bytes
                    j_slice = self.j_buffer[0:bytes_read]
                    raw_data = bytes(b & 0xff for b in j_slice)
                    self.queue.put(raw_data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in Android microphone record loop: {e}")
                break

    def read(self, size):
        """Read data from python queue; blocks until data is available."""
        data = bytearray()
        while len(data) < size and (self.recording or not self.queue.empty()):
            try:
                # block up to 1 second to retrieve audio bytes
                chunk = self.queue.get(timeout=1.0)
                data.extend(chunk)
            except queue.Empty:
                break
        return bytes(data)

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Cleaning up Android AudioRecord resources")
        self.recording = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.audio_record:
            try:
                self.audio_record.stop()
                self.audio_record.release()
            except Exception as e:
                logger.error(f"Error releasing AudioRecord: {e}")
            self.audio_record = None
        self.j_buffer = None


# ==========================================
# 2. Platform-aware Text-to-Speech Engine
# ==========================================
class TTSEngine:
    """
    Platform-aware TTS Engine. Uses pyttsx3 on desktop and
    android.speech.tts.TextToSpeech via Pyjnius on Android.
    """
    def __init__(self):
        self.android_tts = None
        self.Locale = None
        
        if platform == 'android':
            try:
                from jnius import autoclass
                Locale = autoclass('java.util.Locale')
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
                
                self.Locale = Locale
                # Initialize native TTS on Android using the Kivy Activity context
                self.android_tts = TextToSpeech(PythonActivity.mActivity, None)
                logger.info("Android TextToSpeech engine initialized")
            except Exception as e:
                logger.error(f"Failed to load Android TTS: {e}", exc_info=True)
        else:
            try:
                import pyttsx3
                self.desktop_tts = pyttsx3.init()
                # Configure desktop voices
                voices = self.desktop_tts.getProperty('voices')
                if voices:
                    self.desktop_tts.setProperty('voice', voices[0].id)
                self.desktop_tts.setProperty('rate', 175)  # slightly faster speaking speed
                logger.info("Desktop pyttsx3 engine initialized")
            except Exception as e:
                logger.error(f"Failed to load Desktop pyttsx3 engine: {e}")
                self.desktop_tts = None

    def speak(self, text):
        """Speaks the text out loud in a thread-safe, non-blocking manner."""
        logger.info(f"Speaking: '{text}'")
        if platform == 'android' and self.android_tts:
            try:
                from jnius import autoclass
                TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
                self.android_tts.setLanguage(self.Locale.US)
                # Call overloaded speak method
                self.android_tts.speak(text, TextToSpeech.QUEUE_FLUSH, None)
            except Exception as e:
                logger.error(f"Android TTS speak error: {e}")
        elif hasattr(self, 'desktop_tts') and self.desktop_tts:
            try:
                # Desktop pyttsx3.runAndWait() blocks the GUI thread.
                # We spawn a single-use background thread to perform desktop speech.
                def _speak_thread():
                    try:
                        self.desktop_tts.say(text)
                        self.desktop_tts.runAndWait()
                    except Exception as ex:
                        logger.error(f"Error in desktop speech thread: {ex}")
                threading.Thread(target=_speak_thread, daemon=True).start()
            except Exception as e:
                logger.error(f"Desktop speech invocation error: {e}")
        else:
            logger.warning(f"No speech engine available. TTS output: '{text}'")

    def is_speaking(self):
        """Checks if the speech engine is currently active."""
        if platform == 'android' and self.android_tts:
            try:
                return self.android_tts.isSpeaking()
            except Exception as e:
                logger.error(f"Error checking Android speech status: {e}")
                return False
        # Desktop pyttsx3 does not expose a reliable real-time isSpeaking check easily.
        # We assume speech takes roughly 0.15s per word.
        return False


# ==========================================
# 3. OpenAI Client Integration
# ==========================================
class OpenAIClient:
    """Interacts with the OpenAI API for fallback chatbot interactions."""
    def __init__(self, api_key=""):
        self.api_key = api_key
        self.chat_history = []
        
    def set_key(self, api_key):
        self.api_key = api_key.strip()
        
    def has_key(self):
        return bool(self.api_key and "YOUR_OPENAI_API_KEY" not in self.api_key)

    def query(self, prompt):
        """Sends the prompt to GPT-3.5-Turbo and returns the response."""
        if not self.has_key():
            return "OpenAI API Key is not set. Please configure it in Settings."
            
        import requests
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Maintain simple history: keep last 5 exchanges
        self.chat_history.append({"role": "user", "content": prompt})
        if len(self.chat_history) > 10:
            self.chat_history = self.chat_history[-10:]
            
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are a helpful Android voice assistant. Keep answers brief and conversational."}
            ] + self.chat_history,
            "max_tokens": 150,
            "temperature": 0.7
        }
        
        try:
            logger.info("Sending prompt to OpenAI API...")
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=12
            )
            if response.status_code == 200:
                data = response.json()
                reply = data["choices"][0]["message"]["content"].strip()
                self.chat_history.append({"role": "assistant", "content": reply})
                return reply
            else:
                logger.error(f"OpenAI error response: {response.text}")
                return f"AI connection error: status code {response.status_code}."
        except Exception as e:
            logger.error(f"Failed to query OpenAI API: {e}")
            return "Sorry, I had trouble connecting to my AI brain."


# ==========================================
# 4. Kivy UI and Layout Files
# ==========================================
Builder.load_string("""
#:import Factory kivy.factory.Factory

<MessageLabel@Label>:
    text_size: self.width, None
    size_hint_y: None
    height: self.texture_size[1]
    padding: [12, 12]
    valign: 'middle'

<MessageBubble>:
    orientation: 'vertical'
    size_hint_y: None
    height: msg_lbl.height + 30
    padding: [10, 5]
    spacing: 5
    
    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: msg_lbl.height + 20
        
        Widget:
            size_hint_x: None
            width: 55 if root.align_right else 0
            
        BoxLayout:
            orientation: 'vertical'
            canvas.before:
                Color:
                    rgba: root.bubble_color
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [16, 16, (0 if root.align_right else 16), (16 if root.align_right else 0)]
            padding: [12, 8]
            
            Label:
                text: root.sender
                font_size: '11sp'
                bold: True
                color: [0.35, 0.78, 0.98, 1] if root.align_right else [0.65, 0.65, 0.65, 1]
                size_hint_y: None
                height: 15
                text_size: self.width, None
                halign: 'right' if root.align_right else 'left'
                
            MessageLabel:
                id: msg_lbl
                text: root.text
                color: root.text_color
                halign: 'right' if root.align_right else 'left'
                font_size: '14.5sp'
                
        Widget:
            size_hint_x: None
            width: 0 if root.align_right else 55

<MicButton>:
    size_hint: None, None
    size: [90, 90]
    pos_hint: {'center_x': 0.5}
    
    canvas.before:
        # Pulsing circle 1
        Color:
            rgba: [0.0, 0.88, 1.0, self.pulse_opacity1]
        Ellipse:
            pos: [self.center_x - self.pulse_radius1, self.center_y - self.pulse_radius1]
            size: [self.pulse_radius1 * 2, self.pulse_radius1 * 2]
            
        # Pulsing circle 2
        Color:
            rgba: [0.73, 0.33, 0.98, self.pulse_opacity2]
        Ellipse:
            pos: [self.center_x - self.pulse_radius2, self.center_y - self.pulse_radius2]
            size: [self.pulse_radius2 * 2, self.pulse_radius2 * 2]
            
        # Outer core ring
        Color:
            rgba: [1, 1, 1, 0.15]
        Ellipse:
            pos: [self.x - 4, self.y - 4]
            size: [self.width + 8, self.height + 8]
            
        # Center circle
        Color:
            rgba: self.state_color
        Ellipse:
            pos: self.pos
            size: self.size
            
    text: '🎤'
    font_size: '36sp'
    color: [1, 1, 1, 1]
    halign: 'center'
    valign: 'middle'

BoxLayout:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: [0.07, 0.08, 0.1, 1]
        Rectangle:
            pos: self.pos
            size: self.size
            
    # Header bar
    BoxLayout:
        size_hint_y: None
        height: 60
        padding: [15, 10]
        canvas.before:
            Color:
                rgba: [0.12, 0.14, 0.17, 1]
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: 'Antigravity Assistant'
            font_size: '18sp'
            bold: True
            color: [0.0, 0.88, 1.0, 1]
            halign: 'left'
            valign: 'middle'
            text_size: self.size
        Button:
            text: '⚙️'
            font_size: '22sp'
            size_hint_x: None
            width: 50
            background_color: [0, 0, 0, 0]
            on_release: app.open_settings_popup()
            
    # Scrollable Log Window
    ScrollView:
        id: chat_scroll
        do_scroll_x: False
        BoxLayout:
            id: chat_container
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: [15, 15]
            spacing: 14
            
    # Status row
    BoxLayout:
        size_hint_y: None
        height: 40
        padding: [15, 5]
        spacing: 10
        canvas.before:
            Color:
                rgba: [0.09, 0.1, 0.12, 1]
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: 'Status: ' + app.status_text
            color: app.status_color
            font_size: '13.5sp'
            bold: True
            size_hint_x: 0.6
            halign: 'left'
            valign: 'middle'
            text_size: self.size
        BoxLayout:
            size_hint_x: 0.4
            orientation: 'horizontal'
            spacing: 5
            CheckBox:
                id: continuous_toggle
                active: True
                size_hint_x: None
                width: 30
            Label:
                text: 'Auto Listen'
                font_size: '12sp'
                color: [0.75, 0.75, 0.75, 1]
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                
    # Lower control area
    BoxLayout:
        size_hint_y: None
        height: 145
        orientation: 'vertical'
        padding: [12, 10, 12, 10]
        spacing: 10
        
        # TextInput fallback
        BoxLayout:
            size_hint_y: None
            height: 42
            spacing: 8
            TextInput:
                id: query_input
                hint_text: 'Type a command...'
                multiline: False
                background_color: [0.15, 0.17, 0.2, 1]
                foreground_color: [1, 1, 1, 1]
                cursor_color: [0.0, 0.88, 1.0, 1]
                font_size: '14sp'
                hint_text_color: [0.5, 0.5, 0.5, 1]
                padding: [10, 10, 10, 10]
                on_text_validate: app.send_manual_query(self.text); self.text = ''
            Button:
                text: 'Send'
                size_hint_x: None
                width: 70
                background_color: [0.0, 0.45, 0.65, 1]
                color: [1, 1, 1, 1]
                bold: True
                on_release: app.send_manual_query(query_input.text); query_input.text = ''
                
        # Mic trigger
        AnchorLayout:
            anchor_x: 'center'
            anchor_y: 'center'
            size_hint_y: None
            height: 75
            MicButton:
                id: mic_btn
                state_color: app.mic_state_color
                on_release: app.toggle_listening()
""")


# ==========================================
# 5. Message Bubble Widget
# ==========================================
class MessageBubble(BoxLayout):
    sender = StringProperty('')
    text = StringProperty('')
    text_color = ColorProperty([1, 1, 1, 1])
    bubble_color = ColorProperty([0.15, 0.17, 0.2, 1])
    align_right = NumericProperty(0)  # 0: left (assistant), 1: right (user)


# ==========================================
# 6. Mic Button Widget (Custom shapes/pulses)
# ==========================================
class MicButton(Button):
    pulse_radius1 = NumericProperty(45)
    pulse_opacity1 = NumericProperty(0.0)
    pulse_radius2 = NumericProperty(45)
    pulse_opacity2 = NumericProperty(0.0)
    state_color = ColorProperty([0.2, 0.22, 0.25, 1])


# ==========================================
# 7. Main VoiceAssistant Application Class
# ==========================================
class VoiceAssistantApp(App):
    status_text = StringProperty("Idle")
    status_color = ColorProperty([0.5, 0.5, 0.5, 1])  # Gray
    mic_state_color = ColorProperty([0.2, 0.22, 0.25, 1])  # Default gray-blue
    
    def __init__(self, **kwargs):
        super(VoiceAssistantApp, self).__init__(**kwargs)
        self.tts_engine = None
        self.openai_client = None
        self.config_data = {}
        self.continuous_listening = True
        self.mic_active = False
        
        # Audio input recognition components
        self.recognizer = sr.Recognizer()
        # Adjust recognizer sensitivity
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.energy_threshold = 250
        
        # Threading control
        self.worker_thread = None
        self.running = True
        self.trigger_listening_event = threading.Event()
        
    def build(self):
        # Load configuration file
        self.load_config()
        
        # Instantiate Engines
        self.tts_engine = TTSEngine()
        self.openai_client = OpenAIClient(self.config_data.get("openai_api_key", ""))
        
        # Ask for dynamic permissions on Android launch
        self.request_permissions_android()
        
        # Start background polling/processing thread
        self.worker_thread = threading.Thread(target=self.assistant_worker_loop, name="VoiceWorker")
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
        logger.info("UI built and background thread launched.")
        
        # Greet user
        Clock.schedule_once(lambda dt: self.add_message("Assistant", "Hello! I am your Antigravity Assistant. Press the microphone button or type a command to start.", False), 0.5)
        Clock.schedule_once(lambda dt: self.tts_engine.speak("Hello! I am your Antigravity Assistant. How can I help you?"), 1.0)
        
        # The UI root layout was loaded once near the top of this module
        # via Builder.load_string("""...""")
        return self.root if hasattr(self, 'root') else Widget()



    # ------------------------------------------
    # Configuration File Handlers
    # ------------------------------------------
    def get_config_filepath(self):
        """Returns the appropriate, writable config file path based on platform."""
        if platform == 'android':
            try:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                activity = PythonActivity.mActivity
                files_dir = activity.getFilesDir().getAbsolutePath()
                return os.path.join(files_dir, "config.json")
            except Exception as e:
                logger.error(f"Failed to resolve Android files directory: {e}")
                return "config.json"
        return "config.json"

    def load_config(self):
        path = self.get_config_filepath()
        logger.info(f"Loading config from {path}")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                logger.error(f"Error reading config: {e}")
                self.config_data = {}
        else:
            self.config_data = {"openai_api_key": "YOUR_OPENAI_API_KEY_HERE"}
            self.save_config()

    def save_config(self):
        path = self.get_config_filepath()
        logger.info(f"Saving config to {path}")
        try:
            with open(path, 'w') as f:
                json.dump(self.config_data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    # ------------------------------------------
    # Android Permissions
    # ------------------------------------------
    def request_permissions_android(self):
        """Requests required Android permissions at runtime."""
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                # Request MIC permissions dynamically
                request_permissions([Permission.RECORD_AUDIO])
                logger.info("Android permissions requested")
            except Exception as e:
                logger.error(f"Failed requesting Android permissions: {e}")

    # ------------------------------------------
    # GUI Message Logging & Helpers
    # ------------------------------------------
    @mainthread
    def add_message(self, sender, text, align_right=False):
        """Inserts a styled chat bubble into the conversation layout."""
        bubble = MessageBubble(
            sender=sender,
            text=text,
            align_right=1 if align_right else 0,
            bubble_color=[0.07, 0.45, 0.65, 1] if align_right else [0.15, 0.17, 0.20, 1]
        )
        self.root.ids.chat_container.add_widget(bubble)
        # Schedule scroll-down adjustment
        Clock.schedule_once(self.scroll_to_bottom, 0.1)

    def scroll_to_bottom(self, dt):
        self.root.ids.chat_scroll.scroll_y = 0.0

    @mainthread
    def set_status(self, text, color, mic_color):
        """Thread-safe update of assistant status indicators."""
        self.status_text = text
        self.status_color = color
        self.mic_state_color = mic_color
        
        # Stop or start microphone animations
        mic_btn = self.root.ids.mic_btn
        if text == "Listening...":
            self.start_pulse_animation(mic_btn)
        else:
            self.stop_pulse_animation(mic_btn)

    # ------------------------------------------
    # Pulsing Ring Animations
    # ------------------------------------------
    def start_pulse_animation(self, widget):
        widget.pulse_radius1 = 45
        widget.pulse_opacity1 = 0.8
        widget.pulse_radius2 = 45
        widget.pulse_opacity2 = 0.8
        
        self.anim1 = Animation(pulse_radius1=110, pulse_opacity1=0.0, duration=1.6)
        self.anim2 = Animation(pulse_radius2=135, pulse_opacity2=0.0, duration=2.2)
        
        self.anim1.repeat = True
        self.anim2.repeat = True
        
        self.anim1.start(widget)
        # Stagger the launch of the second ring
        Clock.schedule_once(lambda dt: self.anim2.start(widget) if self.status_text == "Listening..." else None, 0.6)

    def stop_pulse_animation(self, widget):
        if hasattr(self, 'anim1'):
            self.anim1.stop(widget)
        if hasattr(self, 'anim2'):
            self.anim2.stop(widget)
        widget.pulse_radius1 = 45
        widget.pulse_opacity1 = 0.0
        widget.pulse_radius2 = 45
        widget.pulse_opacity2 = 0.0

    # ------------------------------------------
    # Interaction Controls
    # ------------------------------------------
    def toggle_listening(self):
        """Triggered when the user presses the main circular mic button."""
        if self.status_text == "Listening...":
            logger.info("Manually stopping recording listener")
            # Clear trigger to stop continuous listening
            self.trigger_listening_event.clear()
            self.set_status("Idle", [0.5, 0.5, 0.5, 1], [0.2, 0.22, 0.25, 1])
        else:
            logger.info("Manually initiating recording listener")
            self.trigger_listening_event.set()

    def send_manual_query(self, text):
        """Called when a user types text in the bottom bar and taps Send."""
        query = text.strip()
        if not query:
            return
            
        self.add_message("You", query, True)
        
        # Run processing thread for this query
        def _process():
            self.set_status("Processing...", [1.0, 0.8, 0.0, 1], [0.8, 0.6, 0.0, 1])
            self.process_command(query)
            
        threading.Thread(target=_process, daemon=True).start()

    # ------------------------------------------
    # Background Processing Thread
    # ------------------------------------------
    def assistant_worker_loop(self):
        """Continuous background thread handling STT capture loop."""
        while self.running:
            # Check if continuous listening or a manual trigger is active
            is_auto = self.root.ids.continuous_toggle.active
            
            if not is_auto and not self.trigger_listening_event.is_set():
                # Idle state
                self.set_status("Idle", [0.5, 0.5, 0.5, 1], [0.2, 0.22, 0.25, 1])
                self.trigger_listening_event.wait(0.5)
                continue
                
            # If speaking is active, wait for it to finish first
            if self.tts_engine.is_speaking():
                time.sleep(0.2)
                continue
                
            # Start listening sequence
            self.set_status("Listening...", [0.0, 0.88, 1.0, 1], [0.0, 0.6, 0.7, 1])
            
            # Setup Platform Audio Source
            source = None
            try:
                if platform == 'android':
                    source = AndroidMicrophone()
                else:
                    source = sr.Microphone()
            except Exception as e:
                logger.error(f"Could not open microphone: {e}")
                self.add_message("System", f"Microphone error: {e}. Please check permissions.", False)
                self.set_status("Error", [1.0, 0.0, 0.0, 1], [0.5, 0.1, 0.1, 1])
                time.sleep(3.0)
                # clear trigger to avoid crash loops
                self.trigger_listening_event.clear()
                continue
                
            audio = None
            try:
                with source as s:
                    # Listen for up to 5 seconds of silence, with a maximum 8 seconds phrase limit
                    audio = self.recognizer.listen(s, timeout=5.0, phrase_time_limit=8.0)
            except sr.WaitTimeoutError:
                # No speech captured, recycle loop silently
                logger.info("Speech recognition timeout - no audio detected")
            except Exception as e:
                logger.error(f"Error capturing audio: {e}")
                
            # Clear manual trigger so we don't repeat unless Auto Listen is on
            self.trigger_listening_event.clear()
            
            if audio:
                self.set_status("Processing...", [1.0, 0.8, 0.0, 1], [0.8, 0.6, 0.0, 1])
                try:
                    logger.info("Transcribing audio...")
                    transcription = self.recognizer.recognize_google(audio)
                    logger.info(f"Transcribed: '{transcription}'")
                    self.add_message("You", transcription, True)
                    
                    # Process the transcription
                    self.process_command(transcription)
                except sr.UnknownValueError:
                    logger.info("Google Speech Recognition could not understand audio")
                    self.add_message("Assistant", "Sorry, I couldn't quite hear you. Could you repeat that?", False)
                    self.tts_engine.speak("Sorry, I couldn't quite hear you.")
                except sr.RequestError as e:
                    logger.error(f"Google Speech Recognition connection error: {e}")
                    self.add_message("Assistant", "Speech service is currently unavailable. Try typing your command.", False)
                    self.tts_engine.speak("Speech service is currently offline.")
                except Exception as e:
                    logger.error(f"Transcription error: {e}")
                    
            # Small cooldown before restarting listening cycle
            time.sleep(0.5)

    # ------------------------------------------
    # Local Intents & fallback to OpenAI GPT
    # ------------------------------------------
    def process_command(self, command):
        """Resolves rule-based commands locally or routes them to OpenAI ChatGPT."""
        # 1. Resolve Intents locally
        intent = self.resolve_local_intent(command)
        
        if intent:
            action, target, speech_response = intent
            logger.info(f"Matched local intent: {action} with target {target}")
            
            # Display and Speak Response
            self.add_message("Assistant", speech_response, False)
            self.set_status("Speaking...", [0.73, 0.33, 0.98, 1], [0.55, 0.2, 0.75, 1])
            self.tts_engine.speak(speech_response)
            
            # Wait briefly for speaking to initiate before performing screen action
            time.sleep(0.8)
            self.execute_native_action(action, target)
            
        else:
            # 2. Fallback to OpenAI ChatGPT
            logger.info("No local intent matched. Routing to OpenAI...")
            if self.openai_client.has_key():
                ai_response = self.openai_client.query(command)
                self.add_message("Assistant", ai_response, False)
                self.set_status("Speaking...", [0.73, 0.33, 0.98, 1], [0.55, 0.2, 0.75, 1])
                self.tts_engine.speak(ai_response)
            else:
                fallback_msg = "Command not recognized locally, and no OpenAI API Key is configured. Tap the Settings icon at the top to set it up!"
                self.add_message("Assistant", fallback_msg, False)
                self.set_status("Speaking...", [0.73, 0.33, 0.98, 1], [0.55, 0.2, 0.75, 1])
                self.tts_engine.speak("I don't know how to do that yet. Please set up your API key for advanced AI queries.")

    def resolve_local_intent(self, command):
        """Matches core intent strings and extracts metadata."""
        cmd = command.lower().strip().replace(".", "").replace("?", "").replace("!", "")
        
        # Local Intent matching
        if cmd == "open youtube":
            return ("open_app", "com.google.android.youtube", "Opening YouTube")
        elif cmd == "open whatsapp":
            return ("open_app", "com.whatsapp", "Opening WhatsApp")
        elif cmd == "open instagram":
            return ("open_app", "com.instagram.android", "Opening Instagram")
        elif cmd in ["open chrome", "open browser"]:
            return ("open_app", "com.android.chrome", "Opening Chrome browser")
        elif cmd == "open settings":
            return ("open_settings", None, "Opening Android Settings")
            
        elif cmd.startswith("search google for "):
            query = command[18:].strip()
            return ("search_google", query, f"Searching Google for {query}")
        elif cmd.startswith("search for "):
            query = command[11:].strip()
            return ("search_google", query, f"Searching Google for {query}")
            
        elif any(q in cmd for q in ["what time is it", "what is the time", "tell me the time"]):
            current_time = datetime.datetime.now().strftime("%I:%M %p")
            return ("speak", current_time, f"The time is {current_time}")
            
        elif any(q in cmd for q in ["what is the date", "what is today's date", "tell me today's date"]):
            current_date = datetime.datetime.now().strftime("%B %d, %Y")
            return ("speak", current_date, f"Today's date is {current_date}")
            
        return None

    def execute_native_action(self, action, target):
        """Triggers native Android features via Pyjnius, with cross-platform desktop fallbacks."""
        if action == "open_app":
            if platform == 'android':
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass('org.kivy.android.PythonActivity')
                    Intent = autoclass('android.content.Intent')
                    activity = PythonActivity.mActivity
                    pm = activity.getPackageManager()
                    
                    # Fetch launch intent for the requested package
                    intent = pm.getLaunchIntentForPackage(target)
                    if intent:
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        activity.startActivity(intent)
                        logger.info(f"Successfully launched Android app: {target}")
                    else:
                        logger.warning(f"App package not found on device: {target}")
                        # Try web browser fallback
                        web_fallbacks = {
                            "com.google.android.youtube": "https://youtube.com",
                            "com.whatsapp": "https://web.whatsapp.com",
                            "com.instagram.android": "https://instagram.com",
                            "com.android.chrome": "https://google.com"
                        }
                        webbrowser.open(web_fallbacks.get(target, "https://google.com"))
                except Exception as e:
                    logger.error(f"Android JNI app launch failed: {e}")
            else:
                # Desktop browser simulation fallback
                web_fallbacks = {
                    "com.google.android.youtube": "https://youtube.com",
                    "com.whatsapp": "https://web.whatsapp.com",
                    "com.instagram.android": "https://instagram.com",
                    "com.android.chrome": "https://google.com"
                }
                webbrowser.open(web_fallbacks.get(target, "https://google.com"))
                
        elif action == "open_settings":
            if platform == 'android':
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass('org.kivy.android.PythonActivity')
                    Intent = autoclass('android.content.Intent')
                    Settings = autoclass('android.provider.Settings')
                    
                    activity = PythonActivity.mActivity
                    # Launch native Android main Settings panel
                    intent = Intent(Settings.ACTION_SETTINGS)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    activity.startActivity(intent)
                    logger.info("Successfully opened Android settings activity")
                except Exception as e:
                    logger.error(f"Android JNI settings launch failed: {e}")
            else:
                # Desktop control panel settings fallback
                logger.info("Opening desktop settings control panel")
                try:
                    if sys.platform == "win32":
                        os.system("control.exe")
                    elif sys.platform == "darwin":
                        import subprocess
                        subprocess.Popen(["open", "/System/Applications/System Settings.app"])
                    else:
                        import subprocess
                        subprocess.Popen(["xdg-open", "settings"])
                except Exception as e:
                    logger.error(f"Failed to open desktop settings: {e}")
                    
        elif action == "search_google":
            # Direct query url
            url = f"https://www.google.com/search?q={target}"
            if platform == 'android':
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass('org.kivy.android.PythonActivity')
                    Intent = autoclass('android.content.Intent')
                    Uri = autoclass('android.net.Uri')
                    
                    activity = PythonActivity.mActivity
                    intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    activity.startActivity(intent)
                    logger.info(f"Opened Android browser search for: {target}")
                except Exception as e:
                    logger.error(f"Android browser intent failed: {e}")
                    webbrowser.open(url)
            else:
                webbrowser.open(url)

    # ------------------------------------------
    # Settings Gear / OpenAI API Configuration UI
    # ------------------------------------------
    def open_settings_popup(self):
        """Displays a Kivy Popup modal to input/update the OpenAI API key."""
        popup_layout = BoxLayout(orientation='vertical', padding=15, spacing=15)
        
        label = Label(
            text="Configure OpenAI API Key\n(Required for general AI fallback features)",
            halign='center',
            size_hint_y=None,
            height=50,
            font_size='14sp'
        )
        popup_layout.add_widget(label)
        
        # Text Input
        key_input = TextInput(
            text=self.config_data.get("openai_api_key", ""),
            multiline=False,
            password=True,
            background_color=[0.15, 0.17, 0.2, 1],
            foreground_color=[1, 1, 1, 1],
            cursor_color=[0.0, 0.88, 1.0, 1],
            font_size='14sp',
            padding=[10, 10, 10, 10],
            size_hint_y=None,
            height=45
        )
        popup_layout.add_widget(key_input)
        
        # Show/Hide Key toggle
        toggle_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=35, spacing=10)
        show_chk = CheckBox(size_hint_x=None, width=30)
        show_chk.bind(active=lambda checkbox, value: setattr(key_input, 'password', not value))
        show_lbl = Label(text="Show API Key", halign='left', valign='middle')
        show_lbl.bind(size=lambda s, w: setattr(show_lbl, 'text_size', w))
        toggle_layout.add_widget(show_chk)
        toggle_layout.add_widget(show_lbl)
        popup_layout.add_widget(toggle_layout)
        
        # Button controls
        btn_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=45)
        
        save_btn = Button(
            text="Save Key",
            background_color=[0.0, 0.55, 0.45, 1],
            bold=True
        )
        cancel_btn = Button(
            text="Cancel",
            background_color=[0.6, 0.2, 0.2, 1],
            bold=True
        )
        
        btn_layout.add_widget(save_btn)
        btn_layout.add_widget(cancel_btn)
        popup_layout.add_widget(btn_layout)
        
        # Popup shell instantiation
        settings_popup = Popup(
            title="Application Settings",
            content=popup_layout,
            size_hint=(None, None),
            size=(340, 290),
            background_color=[0.07, 0.08, 0.1, 0.95]
        )
        
        # Binding Actions
        def _save(instance):
            new_key = key_input.text.strip()
            self.config_data["openai_api_key"] = new_key
            self.save_config()
            self.openai_client.set_key(new_key)
            self.add_message("System", "OpenAI API Key successfully updated.", False)
            settings_popup.dismiss()
            
        save_btn.bind(on_release=_save)
        cancel_btn.bind(on_release=settings_popup.dismiss)
        
        settings_popup.open()

    def on_stop(self):
        """Fires when the Kivy application window is closing."""
        logger.info("Stopping Voice Assistant App...")
        self.running = False
        # Unblock polling thread
        self.trigger_listening_event.set()
        if self.worker_thread:
            self.worker_thread.join(timeout=1.0)
        logger.info("Voice Assistant App successfully terminated")


if __name__ == '__main__':
    VoiceAssistantApp().run()
