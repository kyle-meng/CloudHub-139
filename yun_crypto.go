package main

import (
	"bytes"
	"compress/gzip"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"os"
)

type YunCrypto struct {
	Key       []byte
	BlockSize int
}

func NewYunCrypto() *YunCrypto {
	return &YunCrypto{
		Key:       []byte("PVGDwmcvfs1uV3d1"),
		BlockSize: aes.BlockSize,
	}
}

// PKCS7Padding 填充
func (y *YunCrypto) PKCS7Padding(ciphertext []byte, blockSize int) []byte {
	padding := blockSize - len(ciphertext)%blockSize
	padtext := bytes.Repeat([]byte{byte(padding)}, padding)
	return append(ciphertext, padtext...)
}

// PKCS7UnPadding 移除填充
func (y *YunCrypto) PKCS7UnPadding(origData []byte) ([]byte, error) {
	length := len(origData)
	if length == 0 {
		return nil, errors.New("data is empty")
	}
	unpadding := int(origData[length-1])
	if length < unpadding {
		return nil, errors.New("unpadding error")
	}
	return origData[:(length - unpadding)], nil
}

// Encrypt 将 Map/Struct 加密为 Base64 字符串
func (y *YunCrypto) Encrypt(data interface{}) (string, error) {
	// 1. JSON 序列化 (对应 Python 的 separators=(',', ':'))
	jsonData, err := json.Marshal(data)
	if err != nil {
		return "", err
	}

	// 2. 生成随机 IV
	iv := make([]byte, y.BlockSize)
	if _, err := io.ReadFull(rand.Reader, iv); err != nil {
		return "", err
	}

	// 3. 填充并加密
	block, err := aes.NewCipher(y.Key)
	if err != nil {
		return "", err
	}
	content := y.PKCS7Padding(jsonData, y.BlockSize)
	ciphertext := make([]byte, len(content))
	mode := cipher.NewCBCEncrypter(block, iv)
	mode.CryptBlocks(ciphertext, content)

	// 4. 拼接 IV + 密文并 Base64 编码
	result := append(iv, ciphertext...)
	return base64.StdEncoding.EncodeToString(result), nil
}

// Decrypt 解密 Base64 字符串，支持 Gzip 处理
func (y *YunCrypto) Decrypt(b64Data string) (string, error) {
	// 1. Base64 解码 (移除空白字符)
	b64Data = strings.Join(strings.Fields(b64Data), "")
	raw, err := base64.StdEncoding.DecodeString(b64Data)
	if err != nil {
		return "", err
	}

	if len(raw) < y.BlockSize {
		return "", errors.New("data too short")
	}

	// 2. 分离 IV 和密文
	iv := raw[:y.BlockSize]
	ciphertext := raw[y.BlockSize:]

	// 3. AES-CBC 解密
	block, err := aes.NewCipher(y.Key)
	if err != nil {
		return "", err
	}
	decrypted := make([]byte, len(ciphertext))
	mode := cipher.NewCBCDecrypter(block, iv)
	mode.CryptBlocks(decrypted, ciphertext)

	// 4. 检查是否为 Gzip 压缩 (魔数 1f 8b)
	if len(decrypted) > 2 && decrypted[0] == 0x1f && decrypted[1] == 0x8b {
		reader, err := gzip.NewReader(bytes.NewReader(decrypted))
		if err == nil {
			defer reader.Close()
			unzipped, err := io.ReadAll(reader)
			if err == nil {
				return string(unzipped), nil
			}
		}
	}

	// 5. 移除 PKCS7 填充
	unpadded, err := y.PKCS7UnPadding(decrypted)
	if err != nil {
		// 容错处理：如果解密失败，尝试直接转字符串
		return strings.TrimSpace(string(decrypted)), nil
	}

	return string(unpadded), nil
}

// 修改 main 函数来读取文件测试
func main() {
	crypto := NewYunCrypto()

	// 读取测试文件
	content, err := os.ReadFile("large_res.txt")
	if err != nil {
		fmt.Printf("Error reading file: %v\n", err)
		return
	}

	// 尝试解密
	dec, err := crypto.Decrypt(string(content))
	if err != nil {
		fmt.Printf("Decryption failed: %v\n", err)
		return
	}

	fmt.Printf("Successfully decrypted large data! Length: %d\n", len(dec))
	// 打印前 500 个字符看看结构
	if len(dec) > 500 {
		fmt.Println("Preview:", dec[:500])
	} else {
		fmt.Println("Full Data:", dec)
	}
}

