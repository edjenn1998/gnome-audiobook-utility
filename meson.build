project('gnome-audiobook-utility', version: '0.1.1', meson_version: '>=1.2', license: 'AGPL-3.0-only')

python = import('python').find_installation(get_option('python'))
run_command(python, '-c',
  'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw; import sys; sys.exit(0 if (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4,10) and (Adw.get_major_version(), Adw.get_minor_version()) >= (1,5) else "GTK >= 4.10 and Libadwaita >= 1.5 required")',
  check: true)
app_id = 'io.github.edjenn1998.AudiobookUtility'
package_dir = get_option('prefix') / get_option('datadir') / 'audiobook-utility'
config = configuration_data()
config.set('PYTHON', python.full_path())
config.set('PACKAGE_DIR', package_dir)
configure_file(input: 'data/audiobook-utility.in', output: 'audiobook-utility',
  configuration: config, install: true, install_dir: get_option('bindir'), install_mode: 'rwxr-xr-x')
install_subdir('src/audiobook_utility', install_dir: get_option('datadir') / 'audiobook-utility',
  exclude_directories: ['__pycache__'])
install_data('data/' + app_id + '.desktop', install_dir: get_option('datadir') / 'applications')
install_data('data/' + app_id + '.metainfo.xml', install_dir: get_option('datadir') / 'metainfo')
install_data('data/' + app_id + '.svg', install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps')
install_data('LICENSE', 'THIRD_PARTY.md', install_dir: get_option('datadir') / 'licenses/audiobook-utility')
