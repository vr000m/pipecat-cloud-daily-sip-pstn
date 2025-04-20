FROM dailyco/pipecat-base:latest

RUN pip cache purge

COPY ./requirements.txt requirements.txt

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./bot.py bot.py
COPY prompts/ ./prompts/ 
