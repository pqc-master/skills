"""Use a packaged CA store in standalone releases and the system store in source mode."""
import ssl
import sys
import urllib.request


def https_handler():
    if getattr(sys, "frozen", False):
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    else:
        context = ssl.create_default_context()
    return urllib.request.HTTPSHandler(context=context)
