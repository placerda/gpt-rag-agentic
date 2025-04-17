# Escolhe uma imagem base oficial do Python (por exemplo, Python 3.12 slim)
FROM python:3.12-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia os arquivos de requirements
COPY requirements.txt .

# Instala as dependências
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copia o restante do código da aplicação para dentro do container
COPY . .

# Expõe a porta em que a aplicação irá rodar (p.ex.: 8000)
EXPOSE 8000

# Define o comando de entrada: iniciar o servidor Uvicorn com FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
