FROM python:3.11-slim

WORKDIR /app

# 安装构建依赖 (Rust 需要)
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# 安装 uv
RUN pip install uv

# 复制项目文件
# 注意：Context 是 backend/
COPY app/engine /app/app/engine
COPY native /app/native
COPY Cargo.toml /app/Cargo.toml

# 安装依赖 & 编译扩展
WORKDIR /app/app/engine
# 使用 system python 环境
RUN uv pip install --system -e .

# 回到根目录以便 main.py 正确运行 (如果有相对路径依赖)
WORKDIR /app

CMD ["python", "app/engine/main.py", "worker"]
