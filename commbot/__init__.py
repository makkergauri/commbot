"""
CommBot - multilingual crisis communication over SMS and voice.

The rough flow is:
    official feeds -> extract facts -> score & target -> localize -> SMS / IVR

Every module here is small on purpose. When something breaks at 2am during
a flood, you want to be able to read the code in five minutes.
"""
__version__ = "0.1.0"