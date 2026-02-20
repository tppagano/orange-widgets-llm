# This is a namespace package (PEP 420 implicit namespace package)
# For compatibility with other orangecontrib packages
__path__ = __import__('pkgutil').extend_path(__path__, __name__)
