{pkgs}: {
  deps = [
    pkgs.dbus
    pkgs.chromium
    pkgs.cups
    pkgs.alsa-lib
    pkgs.cairo
    pkgs.pango
    pkgs.gtk3
    pkgs.glib
    pkgs.xorg.libxcb
    pkgs.xorg.libXrandr
    pkgs.xorg.libXfixes
    pkgs.xorg.libXext
    pkgs.xorg.libXdamage
    pkgs.xorg.libXcomposite
    pkgs.xorg.libX11
    pkgs.libxkbcommon
    pkgs.mesa
    pkgs.libdrm
    pkgs.atk
    pkgs.at-spi2-atk
    pkgs.nspr
    pkgs.nss
  ];
}
