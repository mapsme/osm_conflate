from setuptools import setup
from os import path

here = path.abspath(path.dirname(__file__))
exec(open(path.join(here, 'conflate', 'version.py')).read())

setup(
    name='osm_conflate',
    version=__version__,
    author='Ilya Zverev',
    author_email='ilya@zverev.info',
    packages=['conflate'],
    install_requires=[
        'kdtree',
        'requests',
    ],
    url='https://github.com/mapsme/osm_conflate',
    license='Apache License 2.0',
    description='Command-line script for merging points from a third-party source with OpenStreetMap data',
    long_description=open(path.join(here, 'README.rst')).read(),
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Topic :: Utilities',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3 :: Only',
    ],
    entry_points={
        'console_scripts': ['conflate = conflate:run']
    },
)
