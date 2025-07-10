{pkgs ? import <nixpkgs> {}}: let
  # Create a Python environment with all our packages
  pythonEnv = pkgs.python313.withPackages (ps:
    with ps; [
      # Core Python tools
      pip
      virtualenv
      setuptools
      wheel

      # Project dependencies
      psutil
      pyyaml
      docker
      requests
      prometheus-client
      supervisor

      # Development tools
      pytest
      black
      flake8
      mypy
    ]);
in
  pkgs.mkShell {
    buildInputs = with pkgs; [
      # Use the Python environment we created
      pythonEnv

      # System tools for monitoring
      htop
      iotop
      nethogs

      # Git and misc
      git
      curl
      jq
    ];

    shellHook = ''
      echo "Homelab Monitor Development Environment"
      echo "Python: $(python --version)"
      echo "Supervisor: $(supervisord --version)"
      echo ""
      echo "Available commands:"
      echo "  python run.py           - Start the monitor"
      echo "  supervisord -c config/  - Run with supervisor"
      echo "  pytest                  - Run tests"
      echo "  black .                 - Format code"
      echo "  flake8 .                - Lint code"
      echo "  mypy .                  - Type checking"
      echo ""

      # Create project directories if they don't exist
      mkdir -p logs config data monitors collectors api

      # Set up Python path
      export PYTHONPATH="$PWD:$PYTHONPATH"

      # Set default environment variables
      export MONITOR_CONFIG_PATH="$PWD/config/targets.yaml"
      export MONITOR_LOG_PATH="$PWD/logs"
      export PROMETHEUS_PORT=8000
      export LOG_LEVEL=INFO

      # Test that psutil is available
      python -c "import psutil; print('✓ psutil available')" || echo "✗ psutil not found"
    '';
  }
