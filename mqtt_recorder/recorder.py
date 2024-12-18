import paho.mqtt.client as mqtt
import ssl
import logging
import time
import base64
import csv
import json
from tqdm import tqdm

logging.basicConfig(
    level=logging.DEBUG, 
    format='[%(asctime)s] - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MQTTRecorder')

class SslContext:

    def __init__(self, enable, ca_cert, certfile, keyfile, tls_insecure):
        self.enable = enable
        self.ca_cert = ca_cert
        self.certfile = certfile
        self.keyfile = keyfile
        self.tls_insecure = tls_insecure

class MqttRecorder:

    def __init__(self, host: str, port: int, client_id: str, file_name: str, username: str,
                 password: str, sslContext: SslContext, encode_b64: bool):
        self.__recording = False
        self.__messages = list()
        self.__file_name = file_name
        self.__last_message_time = None
        self.__encode_b64 = encode_b64
        self.__client = mqtt.Client(client_id=client_id)
        self.__client.on_connect = self.__on_connect
        self.__client.on_message = self.__on_message
        
        
        if username is not None:
            self.__client.username_pw_set(username, password)
        
        # SSL/TLS-Configuration
        if sslContext.enable:
            ssl_context = ssl.create_default_context()
            
            # set version to 1.3
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3
            
            # load CA-Certifikate, Client-Certifikate and Key 
            if sslContext.ca_cert:
                ssl_context.load_verify_locations(sslContext.ca_cert)
            if sslContext.certfile and sslContext.keyfile:
                ssl_context.load_cert_chain(certfile=sslContext.certfile, keyfile=sslContext.keyfile)
            
            # accept insecure TLS-Connections, if desired
            if sslContext.tls_insecure:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            self.__client.tls_set_context(ssl_context)
        
        # connect to MQTT-Broker
        self.__client.connect(host=host, port=port)
        self.__client.loop_start()

    def start_recording(self, topics_file: str, qos: int=0):
        self.__last_message_time = time.time()
        if topics_file:
            with open(topics_file) as json_file:
                data = json.load(json_file)
                for topic in data['topics']:
                    self.__client.subscribe(topic, qos=qos)
        else:
            self.__client.subscribe('#', qos=qos)
        self.__recording = True

    def start_replay(self, loop: bool):
        def decode_payload(payload, encode_b64):
            return base64.b64decode(payload) if encode_b64 else payload

        with open(self.__file_name, newline='') as csvfile:
            logger.info('Starting replay')
            first_message = True
            reader = csv.reader(csvfile)
            messages = list(reader)
            while True:
                for row in tqdm(messages, desc='MQTT REPLAY'):
                    if not first_message:
                        time.sleep(float(row[5]))
                    else:
                        first_message = False
                    mqtt_payload = decode_payload(row[1], self.__encode_b64)
                    retain = False if row[3] == '0' else True
                    self.__client.publish(topic=row[0], payload=mqtt_payload,
                                          qos=int(row[2]), retain=retain)
                logger.info('End of replay')
                if loop:
                    logger.info('Restarting replay')
                    time.sleep(1)
                else:
                    break

    def stop_recording(self):
        self.__client.loop_stop()
        logger.info('Recording stopped')
        self.__recording = False
        logger.info('Saving messages to output file')
        with open(self.__file_name, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            for message in self.__messages:
                writer.writerow(message)

    def __on_connect(self, client, userdata, flags, rc):
        logger.info("Connected to broker!")

    def __on_message(self, client, userdata, msg):
        def encode_payload(payload, encode_b64):
            return base64.b64encode(msg.payload).decode() if encode_b64 else payload.decode()

        if self.__recording:
            logger.info("[MQTT Message received] Topic: %s QoS: %s Retain: %s",
                        msg.topic, msg.qos, msg.retain)
            time_now = time.time()
            time_delta = time_now - self.__last_message_time
            payload = encode_payload(msg.payload, self.__encode_b64)
            row = [msg.topic, payload, msg.qos, msg.retain, time_now, time_delta]
            self.__messages.append(row)
            self.__last_message_time = time_now
