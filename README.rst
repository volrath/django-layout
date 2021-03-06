.. {% comment %}

===============
 Django Layout
===============

``django-layout`` provides sane defaults for new Django projects based on `established best practices <http://lincolnloop.com/django-best-practices/>`__. To use ``django-layout`` run the following command::

     django-admin.py startproject --template=https://github.com/volrath/django-layout/zipball/master --extension=py,rst,gitignore,example,conf project_name

.. note:: The text following this comment block will become the README.rst of the new project.

-----

.. {% endcomment %}

{{ project_name }}
==================

Quickstart
----------

To bootstrap the project::

    mkvirtualenv {{ project_name }}
    cd path/to/{{ project_name }}/repository
    pip install -r requirements/local.pip
    pip install -e .
    cp {{ project_name }}/settings/local.py.example {{ project_name }}/settings/local.py
    manage.py syncdb --migrate

Documentation
-------------

Developer documentation is available in Sphinx format in the docs directory.

Initial installation instructions (including how to build the documentation as
HTML) can be found in docs/install.rst.
