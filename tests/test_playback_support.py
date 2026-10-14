import unittest

from tab_tags import SUPPORTED_AUDIO_EXTENSIONS


class PlaybackSupportTests(unittest.TestCase):
    def test_common_audio_extensions_are_supported(self):
        for extension in (".wav", ".aiff", ".mp3", ".flac", ".ogg", ".m4a", ".opus"):
            self.assertIn(extension, SUPPORTED_AUDIO_EXTENSIONS)

    def test_ableton_project_extensions_are_not_audio_extensions(self):
        for extension in (".adv", ".adg", ".als", ".amxd", ".asd"):
            self.assertNotIn(extension, SUPPORTED_AUDIO_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
