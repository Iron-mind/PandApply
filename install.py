"""Bootstrap PandApply in its own virtual environment, then run the guided setup."""

import argparse
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Instalar y configurar PandApply paso a paso")
    parser.add_argument("--configure-only", action="store_true", help="Repetir el asistente sin reinstalar")
    args = parser.parse_args()
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap runs before package requirements are enforced
        parser.error("Necesitas Python 3.11 o posterior")
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    try:
        if not args.configure_only:
            if not (environment / "pyvenv.cfg").is_file():
                if environment.exists():
                    raise ValueError("La carpeta .venv existe pero no es un entorno virtual; revísala antes de continuar")
                print("Preparando el entorno privado de PandApply...", flush=True)
                venv.EnvBuilder(with_pip=True).create(environment)
            if not python.is_file():
                raise ValueError("El entorno .venv está incompleto; revisa su instalación")
            print("Instalando PandApply y sus dependencias...", flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "-e", str(root)], check=True)
        if not python.is_file() or not (environment / "pyvenv.cfg").is_file():
            raise ValueError("Primero ejecuta el instalador sin --configure-only")
        return subprocess.run([str(python), "-m", "pandapply", "setup", "--wizard"], cwd=root, check=False).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo completar la instalación: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInstalación interrumpida. Puedes volver a ejecutar el mismo comando.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
