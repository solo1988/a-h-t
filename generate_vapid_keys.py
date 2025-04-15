from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64

# Генерация приватного ключа
private_key = ec.generate_private_key(ec.SECP256R1())

# Приватный ключ в PEM
pem_private_key = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

# Публичный ключ в формате VAPID (base64url)
public_key = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

vapid_public_key = base64.urlsafe_b64encode(public_key).decode('utf-8').rstrip("=")
vapid_private_key = base64.urlsafe_b64encode(
    private_key.private_numbers().private_value.to_bytes(32, 'big')
).decode('utf-8').rstrip("=")

print("🔐 VAPID Private Key:")
print(vapid_private_key)
print("\n🔑 VAPID Public Key:")
print(vapid_public_key)
