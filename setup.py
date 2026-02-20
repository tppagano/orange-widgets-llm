#!/usr/bin/env python

from setuptools import setup, find_packages
import os

NAME = "Orange3-Chatbot"
VERSION = "0.1.0"
DESCRIPTION = "Orange3 add-on for chatbot with RAG capabilities"
LONG_DESCRIPTION = open(
    os.path.join(os.path.dirname(__file__), "README.md")).read()
AUTHOR = "Chatbot Team"
AUTHOR_EMAIL = "chatbot@example.com"
URL = "https://github.com/yourusername/orange3-chatbot"
LICENSE = "MIT"

KEYWORDS = [
    "orange3 add-on",
    "chatbot",
    "rag",
    "llm",
    "natural language processing"
]

PACKAGES = find_packages()

PACKAGE_DATA = {
    "orangecontrib.chatbot": ["tutorials/*.ows"],
    "orangecontrib.chatbot.widgets": ["icons/*"],
}

CLASSIFIERS = [
    "Development Status :: 3 - Alpha",
    "Environment :: X11 Applications :: Qt",
    "Environment :: Plugins",
    "Programming Language :: Python",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Intended Audience :: Education",
    "Intended Audience :: Science/Research",
    "Intended Audience :: Developers",
]

INSTALL_REQUIRES = [
    "Orange3>=3.31.0",
    "PyQt5>=5.12.0",
    "langchain-community",
    "chromadb",
    "pypdf",
]

EXTRAS_REQUIRE = {
    "dev": [
        "pytest",
        "pytest-cov",
        "black",
    ],
}

ENTRY_POINTS = {
    "orange.widgets": (
        "Chatbot = orangecontrib.chatbot.widgets"
    ),
    "orange3.addon": (
        "orange3-chatbot = orangecontrib.chatbot"
    ),
}

NAMESPACE_PACKAGES = ["orangecontrib"]

if __name__ == "__main__":
    setup(
        name=NAME,
        version=VERSION,
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        long_description_content_type="text/markdown",
        author=AUTHOR,
        author_email=AUTHOR_EMAIL,
        url=URL,
        packages=PACKAGES,
        package_data=PACKAGE_DATA,
        install_requires=INSTALL_REQUIRES,
        extras_require=EXTRAS_REQUIRE,
        entry_points=ENTRY_POINTS,
        keywords=KEYWORDS,
        namespace_packages=NAMESPACE_PACKAGES,
        classifiers=CLASSIFIERS,
        zip_safe=False,
    )
