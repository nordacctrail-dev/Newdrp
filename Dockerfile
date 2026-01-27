# ---------------------------------------------------
# FINAL FIXED DOCKERFILE (With Tkinter support)
# ---------------------------------------------------

# 1. Pin to 'bookworm' (Debian 12 Stable)
FROM python:3.10-slim-bookworm

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Allow pip to install packages globally
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# 2. Install Dependencies
# Added 'python3-tk' and 'python3-dev' to fix the MouseInfo error
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    xvfb \
    libxi6 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libasound2 \
    fonts-liberation \
    python3-tk \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Google Chrome Stable
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable

# 4. Set up the working directory
WORKDIR /app

# 5. Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Optional: Ensure seleniumbase drivers are ready (good practice)
RUN sbase install chromedriver

# 6. Copy application code
COPY . .

# 7. Run the bot
# We use -u to ensure logs stream immediately to Railway console
CMD ["python", "-u", "main.py"]
