# GitLab CI/CD — kurulum ve kararlar

Boru hattı `.gitlab-ci.yml`: **denetim → test → paket → dağıtım**.

## Kararlar

- **Canlı veri CI'a girmez.** Denetim, test ve paket işleri GitLab'ın Docker
  runner'ında, geçici bir PostgreSQL 17 ile koşar. CI paketi `--yalniz-kod`
  ile üretilir: veritabanı dökümü ve yüklenen belgeler pakete girmez (KVKK).
  `ci-dagit.sh` pakette döküm görürse dağıtımı durdurur.
- **İlk kurulum CI ile yapılmaz.** Dökümlü ilk kurulum paketi elle üretilir
  ve KURULUM.md Adım 1–8 ile kurulur. CI yalnız var olan kurulumu yükseltir
  (`kur.sh --veri yok`).
- **Dağıtım her zaman elle başlatılır** (`when: manual`).
  - `dagit:prova`: varsayılan daldan ya da `v*` etiketinden.
  - `dagit:canli`: yalnız `v*` sürüm etiketinden.
- **Sunucuya dışarıdan SSH açılmaz.** Dağıtım işleri sunucunun üzerindeki
  shell runner'da koşar; runner GitLab'a kendisi bağlanır.
- **Sıra:** yedek (alınamazsa dağıtım başlamaz) → paket arşivlenir →
  `kur.sh --veri yok` → `/api/health` ve göç sürümü denetimi → `dogrula.sh`
  (bilgi amaçlı).
- **Geri dönüş otomatik değildir.** KURULUM.md G.6: önce `geri-yukle.sh`, sonra
  önceki paketle `kur.sh`. Son 5 paket `~/denge-paketler` altında saklanır.

## Bir kerelik kurulum

1. **GitLab projesi**
   - Varsayılan dal korumalı olmalı.
   - `v*` etiketleri korumalı olmalı (Settings → Repository → Protected tags).
   - `canli` ortamı Protected environment olmalı; dağıtımı yalnız yetkili
     kişiler başlatabilmeli.
2. **Sunucuda runner**
   - `gitlab-runner` kurulur ve shell executor ile kaydedilir.
   - Etiket: `denge-erp-prova` ya da `denge-erp-canli`.
   - Runner yalnız korumalı dallarda ve etiketlerde koşar ("Protected" işaretli).
3. **sudoers** (`visudo -f /etc/sudoers.d/denge-erp-ci`). Runner'a yalnız
   yedek betiği için parolasız yetki verilir:

   ```
   gitlab-runner ALL=(root) NOPASSWD: /opt/denge-erp/deploy/yedekle.sh
   ```

   `gitlab-runner` kullanıcısı `docker` grubunda olmalı.
4. **Ortam değişkenleri** (GitLab → Settings → CI/CD → Variables):
   - `PROVA_URL` ve `CANLI_URL`: bağlantı için.
   - `DAGITIM_HEDEF`: yalnız `/opt/denge-erp` dışındaysa.

   Parola ya da anahtar GitLab'a konmaz; sırlar sunucudaki `.env` dosyasında kalır.

## Test

`backend:pytest` işi `-m "not slow"` ile koşar. Veritabanına bağlanamazsa iş
düşer; testlerin sessizce atlanıp yeşil görünmesine izin verilmez.
