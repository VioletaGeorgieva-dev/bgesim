from collections import defaultdict
from datetime import datetime
import time
from fastapi import FastAPI, Query, Request, Cookie, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from starlette.middleware.sessions import SessionMiddleware
from app.api.client import check_balance, get_packages, query_esim_usage
from app.services.esim import order_esim
from app.config import settings
from app.translations import (
    SUPPORTED_LANGS,
    translate_country,
    resolve_iso2_from_text,
    get_ui,
)
from app.database import (
    get_affiliate_by_email,
    get_affiliate_by_id,
    get_affiliate_by_promo_code,
    get_all_orders,
    get_order_by_session,
    get_orders_by_promo_code,
    get_esim_tran_no_by_iccid,
    get_order_by_iccid,
    init_db,
    save_order,
    update_affiliate_totals,
)
from pathlib import Path
from typing import Optional, List, Dict, Any
import urllib.parse
import uvicorn
import pycountry
import stripe
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

init_db()

stripe.api_key = settings.stripe_secret_key
APP_ENV = settings.APP_ENV
PARTNER_SESSION_SECRET = settings.partner_session_secret
if not PARTNER_SESSION_SECRET:
    if APP_ENV == "development":
        PARTNER_SESSION_SECRET = "development-partner-session-secret"
    else:
        raise RuntimeError("PARTNER_SESSION_SECRET must be configured")

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="BG eSIM Portal")

USD_TO_EUR = 0.95
MARGIN_COEFFICIENT = 2.0


ADMIN_SESSION_VALUE = "authenticated_admin"
PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ❓ ─── ДАННИ И ПРЕВОДИ ЗА FAQ СТРАНИЦАТА (5 ЕЗИКА) ───
FAQ_DATA = {
    "bg": {
        "title": "❓ Често задавани въпроси (FAQ)",
        "subtitle": "Всичко, което трябва да знаете за вашите BG eSIM карти на едно място.",
        "footer_title": "🚀 Вземете eSIM с високоскоростен интернет",
        "footer_sub": "Пътувайте свободно, без скъп роуминг и без чакане по опашки.",
        "items": [
            {
                "q": "📱 Телефонът ми поддържа ли eSIM?",
                "a": "Повечето съвременни смартфони поддържат eSIM технология.<br>"
                     "• <strong>За iPhone:</strong> Всички модели от iPhone XS, XS Max, XR и по-нови.<br>"
                     "• <strong>За Samsung:</strong> Сериите Galaxy S20, S21, S22, S23, S24, Note 20, Fold и Flip.<br>"
                     "• <strong>За Google Pixel:</strong> Всички модели от Pixel 3 нагоре.<br>"
                     "<em>Бърза проверка: Наберете *#06# от телефона си. Ако на екрана видите EID номер, телефонът ви поддържа eSIM.</em>"
            },
            {
                "q": "🌐 Какво е eSIM и QR код?",
                "a": "<strong>eSIM</strong> е вградена, изцяло дигитална SIM карта. Вече няма нужда да ходите до офис на оператор или да сменяте пластмасови чипове с кламери.<br>"
                     "<strong>QR кодът</strong> е вашият дигитален ключ. Когато го сканирате с камерата на телефона си, устройството ви автоматично изтегля и инсталира интернет профила от разстояние."
            },
            {
                "q": "📲 Как да инсталирам моята BG eSIM?",
                "a": "Имате три лесни начина за инсталация:<br>"
                     "1. <strong>С 1 клик (Най-бързо):</strong> Отворете имейла с потвърждението директно от телефона си и натиснете бутона за вашата операционна система (iOS или Android).<br>"
                     "2. <strong>Чрез QR код:</strong> Сканирайте QR кода от имейла с камерата на телефона си и следвайте инструкциите на екрана.<br>"
                     "3. <strong>Ръчно въвеждане:</strong> Ако нямате второ устройство, под бутоните сме ви оставили 'SM-DP+ адрес' и 'Код за активиране', които можете просто да копирате и поставите в настройките на телефона си."
            },
            {
                "q": "🔄 Вече имам инсталирана eSIM карта, мога ли да добавя друга?",
                "a": "<strong>Да, абсолютно!</strong> Можете да имате инсталирани множество eSIM профили на телефона си (обикновено между 5 и 10, в зависимост от модела). Трябва само да изберете от настройките коя карта да бъде активна в момента."
            },
            {
                "q": "⏳ Кога трябва да закупя eSIM карта?",
                "a": "Най-добре е да направите покупката <strong>1-2 дни преди вашето пътуване</strong>. Можете спокойно да инсталирате профила, докато все още сте у дома и имате стабилен домашен Wi-Fi. Пакетът няма да започне да се изразходва, докато не пристигнете в чужбина."
            },
            {
                "q": "📅 Кога започва валидността на пакета?",
                "a": "За по-голямата част от дестинациите валидността (например 7, 15 или 30 дни) започва <strong>едва когато пристигнете в съответната държава и телефонът ви се свърже с местната партньорска мрежа</strong>. Инсталирането на картата у дома не ви отнема от дните за ползване."
            },
            {
                "q": "🗺️ Мога ли да използвам един и същ eSIM план в множество държави?",
                "a": "Ако закупите пакет за <strong>конкретна държава</strong> (напр. само Гърция), той ще работи само там. Ако пътувате през няколко страни, изберете някой от нашите <strong>Регионални планове</strong> (например 'Европа', който покрива над 30 държави с една-единствена eSIM)."
            },
            {
                "q": "📞 Получавам ли телефонен номер с обаждания и SMS?",
                "a": "Нашите eSIM пакети са предназначени <strong>само за мобилен интернет (Data-only)</strong>. Те не идват с традиционен телефонен номер, но можете да провеждате неограничени безплатни разговори през приложения като <strong>WhatsApp, Viber, Messenger, Telegram или FaceTime</strong>, използвайки нашия бърз интернет."
            },
            {
                "q": "📶 Мога ли да споделям интернет (HotSpot) с моята eSIM?",
                "a": "<strong>Да!</strong> Всички наши eSIM карти поддържат функцията за споделяне на интернет (HotSpot / Tethering). Можете лесно да споделите връзката си с вашия лаптоп, таблет или с телефоните на приятелите ви."
            },
            {
                "q": "📴 Ако използвам eSIM, сегашната ми SIM карта ще работи ли?",
                "a": "<strong>Да, вашата българска SIM карта остава напълно активна.</strong> Телефонът ви преминава в режим 'Dual SIM'. Можете да получавате обаждания и SMS-и на българския си номер, докато eSIM ви осигурява евтиния интернет в чужбина. <em>(Важно: Изберете eSIM за 'Мобилни данни' в настройките си, за да избегнете такси за роуминг от вашия оператор).</em>"
            },
            {
                "q": "📊 Как да видя оставащите си данни?",
                "a": "Много е лесно! Веднага след покупката ви изпращаме втори имейл с линк към вашата <strong>персонална страница за потребление</strong>. Само с 1 клик върху него можете в реално време да виждате колко интернет ви остава."
            }
        ]
    },
    "en": {
        "title": "❓ Frequently Asked Questions (FAQ)",
        "subtitle": "Everything you need to know about your BG eSIM cards in one place.",
        "footer_title": "🚀 Get high-speed internet eSIM now",
        "footer_sub": "Travel freely without expensive roaming and without waiting in lines.",
        "items": [
            {
                "q": "📱 Does my phone support eSIM?",
                "a": "Most modern smartphones support eSIM technology.<br>"
                     "• <strong>For iPhone:</strong> All models from iPhone XS, XS Max, XR and newer.<br>"
                     "• <strong>For Samsung:</strong> Galaxy S20, S21, S22, S23, S24, Note 20, Fold and Flip series.<br>"
                     "• <strong>For Google Pixel:</strong> All models from Pixel 3 and newer.<br>"
                     "<em>Quick check: Dial *#06# on your phone. If you see an EID number, your phone supports eSIM.</em>"
            },
            {
                "q": "🌐 What is an eSIM and QR code?",
                "a": "An <strong>eSIM</strong> is an embedded, entirely digital SIM card. There's no need to visit an operator's office or swap physical plastic chips.<br>"
                     "The <strong>QR code</strong> is your digital key. When you scan it with your phone's camera, your device automatically downloads and installs the internet profile."
            },
            {
                "q": "📲 How do I install my BG eSIM?",
                "a": "You have three easy ways to install:<br>"
                     "1. <strong>One-click (Fastest):</strong> Open the confirmation email directly from your phone and press the button for your OS (iOS or Android).<br>"
                     "2. <strong>QR Code:</strong> Scan the QR code from the email using your phone's camera and follow the on-screen instructions.<br>"
                     "3. <strong>Manual Entry:</strong> If you don't have a second device, we've provided the 'SM-DP+ address' and 'Activation Code' below the buttons, which you can simply copy and paste into your phone settings."
            },
            {
                "q": "🔄 Can I add another eSIM if I already have one installed?",
                "a": "Yes, absolutely! You can have multiple eSIM profiles installed on your phone (usually between 5 and 10, depending on the model). You just need to select which card you want to be active in your settings."
            },
            {
                "q": "⏳ When should I buy an eSIM card?",
                "a": "It is best to make the purchase <strong>1-2 days before your trip</strong>. You can easily install the profile while you are still at home with a stable Wi-Fi connection. The package won't start consuming data until you arrive abroad."
            },
            {
                "q": "📅 When does the package validity begin?",
                "a": "For most destinations, the validity (e.g., 7, 15, or 30 days) starts only when you arrive in the destination country and your phone connects to the local partner network. Installing at home does not take away from your package days."
            },
            {
                "q": "🗺️ Can I use the same eSIM plan in multiple countries?",
                "a": "If you buy a package for a specific country (e.g., Greece only), it will only work there. If you are traveling through multiple countries, choose one of our Regional plans (e.g., 'Europe', which covers over 30 countries with a single eSIM)."
            },
            {
                "q": "📞 Do I get a phone number for calls and SMS?",
                "a": "Our eSIM packages are designed for mobile data only. They do not come with a traditional phone number. However, you can make unlimited free calls and send messages via apps like WhatsApp, Viber, Messenger, Telegram, or FaceTime using our high-speed internet."
            },
            {
                "q": "📶 Can I share internet (HotSpot) with my eSIM?",
                "a": "<strong>Yes!</strong> All our eSIM cards support the internet sharing function (HotSpot / Tethering). You can easily share your connection with your laptop, tablet, or your friends' phones."
            },
            {
                "q": "📴 Will my current SIM card still work if I use an eSIM?",
                "a": "<strong>Yes, your local SIM card remains fully active.</strong> Your phone switches to Dual SIM mode. You can receive calls and SMS on your local number, while the eSIM provides cheap internet abroad. <em>(Important: Select eSIM for 'Mobile Data' in your settings to avoid roaming charges from your domestic carrier).</em>"
            },
            {
                "q": "📊 How can I check my remaining data?",
                "a": "It's very easy! Right after your purchase, we send you a second email with a link to your personal usage page. With just 1 click, you can see how much data you have left in real-time."
            }
        ]
    },
    "de": {
        "title": "❓ Häufig gestellte Fragen (FAQ)",
        "subtitle": "Alles, was Sie über Ihre BG eSIM-Karten wissen müssen, an einem Ort.",
        "footer_title": "🚀 Holen Sie sich jetzt die Highspeed-Internet eSIM",
        "footer_sub": "Reisen Sie frei, ohne teures Roaming und ohne Warteschlangen.",
        "items": [
            {
                "q": "📱 Unterstützt mein Telefon eSIM?",
                "a": "Die meisten modernen Smartphones unterstützen die eSIM-Technologie.<br>"
                     "• <strong>Für iPhone:</strong> Alle Modelle ab iPhone XS, XS Max, XR und neuer.<br>"
                     "• <strong>Für Samsung:</strong> Galaxy S20, S21, S22, S23, S24, Note 20, Fold und Flip Serien.<br>"
                     "• <strong>Für Google Pixel:</strong> Alle Modelle ab Pixel 3 und neuer.<br>"
                     "<em>Schnelltest: Wählen Sie *#06# auf Ihrem Telefon. Wenn Sie eine EID-Nummer sehen, unterstützt Ihr Telefon eSIM.</em>"
            },
            {
                "q": "🌐 Was ist eine eSIM und ein QR-Code?",
                "a": "Eine <strong>eSIM</strong> ist eine integrierte, vollständig digitale SIM-Karte. Sie müssen keinen Mobilfunkshop aufsuchen oder physische SIM-Karten wechseln.<br>"
                     "Der <strong>QR-Code</strong> ist Ihr digitaler Schlüssel. Wenn Sie ihn mit der Kamera Ihres Telefons scannen, lädt Ihr Gerät das Profil automatisch herunter."
            },
            {
                "q": "📲 Wie installiere ich meine BG eSIM?",
                "a": "Sie haben drei superleichte Installationsmöglichkeiten:<br>"
                     "1. <strong>1-Klick (Am schnellsten):</strong> Öffnen Sie die Bestätigungs-E-Mail direkt auf Ihrem Telefon und tippen Sie auf die Schaltfläche für Ihr Betriebssystem (iOS oder Android).<br>"
                     "2. <strong>Über QR-Code:</strong> Scannen Sie den QR-Code aus der E-Mail mit der Kamera Ihres Telefons und folgen Sie den Anweisungen.<br>"
                     "3. <strong>Manuelle Eingabe:</strong> Wenn Sie kein zweites Gerät haben, verwenden Sie die 'SM-DP+ Adresse' und den 'Aktivierungscode' unter den Schaltflächen."
            },
            {
                "q": "🔄 Ich habe bereits eine eSIM installiert, kann ich eine weitere hinzufügen?",
                "a": "Ja, absolut! Sie können mehrere eSIM-Profile auf Ihrem Telefon installieren (je nach Modell meist zwischen 5 und 10). Sie müssen in den Einstellungen lediglich auswählen, welche Karte gerade aktiv sein soll."
            },
            {
                "q": "⏳ Wann sollte ich eine eSIM-Karte kaufen?",
                "a": "Am besten kaufen Sie die eSIM <strong>1-2 Tage vor Ihrer Reise</strong>. Sie können das Profil bequem zu Hause über ein stabilis WLAN installieren. Das Paket verbraucht erst Daten, wenn Sie im Ausland ankommen."
            },
            {
                "q": "📅 Wann beginnt die Gültigkeit des Pakets?",
                "a": "Für die meisten Reiseziele beginnt die Gültigkeit erst, wenn Sie im Zielland ankommen und sich Ihr Telefon mit dem lokalen Partnernetzwerk verbindet. Die Installation zu Hause verkürzt Ihre Laufzeit nicht."
            },
            {
                "q": "🗺️ Kann ich denselben eSIM-Tarif in mehreren Ländern nutzen?",
                "a": "Wenn Sie ein Paket für ein bestimmtes Land kaufen (z. B. nur Griechenland), funktioniert es nur dort. Wenn Sie durch mehrere Länder reisen, wählen Sie einen unserer Regionaltarife (z. B. 'Europa')."
            },
            {
                "q": "📞 Erhalte ich eine Telefonnummer für Anrufe und SMS?",
                "a": "Unsere eSIM-Pakete sind reine Datentarife (Data-only). Sie enthalten keine herkömmliche Telefonnummer. Sie können jedoch unbegrenzt kostenlose Anrufe über Apps wie WhatsApp, Viber oder Messenger tätigen."
            },
            {
                "q": "📶 Kann ich mit meiner eSIM einen Hotspot einrichten?",
                "a": "<strong>Ja!</strong> Alle unsere eSIM-Karten unterstützen die Hotspot-Funktion (Tethering). Sie können Ihre Verbindung ganz einfach mit Ihrem Laptop, Tablet oder anderen Telefonen teilen."
            },
            {
                "q": "📴 Wenn ich eine eSIM verwende, funktioniert meine physische SIM-Karte weiterhin?",
                "a": "<strong>Ja, Ihre normale SIM-Karte bleibt voll aktiv.</strong> Ihr Telefon läuft im Dual-SIM-Modus. Sie können weiterhin Anrufe und SMS auf Ihrer normalen Nummer empfangen, während die eSIM für günstiges Internet sorgt."
            },
            {
                "q": "📊 Wie kann ich mein verbleibendes Datenvolumen einsehen?",
                "a": "Ganz einfach! Direkt nach dem Kauf senden wir Ihnen eine E-Mail mit einem Link zu Ihrer persönlichen Verbrauchseite, auf der Sie Ihr Guthaben in Echtzeit sehen."
            }
        ]
    },
    "tr": {
        "title": "❓ Sıkça Sorulan Sorular (FAQ)",
        "subtitle": "BG eSIM kartlarınız hakkında bilmeniz gereken her şey tek bir yerde.",
        "footer_title": "🚀 Şimdi yüksek hızlı internet ile eSIM alın",
        "footer_sub": "Pahalı roaming ücretleri olmadan ve kuyruklarda beklemeden özgürce seyahat edin.",
        "items": [
            {
                "q": "📱 Telefonum eSIM'i destekliyor mu?",
                "a": "Çoğu modern akıllı telefon eSIM teknolojisini desteklemektedir.<br>"
                     "• <strong>iPhone için:</strong> iPhone XS, XS Max, XR ve daha yeni tüm modeller.<br>"
                     "• <strong>Samsung için:</strong> Galaxy S20, S21, S22, S23, S24, Note 20, Fold ve Flip serileri.<br>"
                     "• <strong>Google Pixel için:</strong> Pixel 3 ve daha yeni tüm modeller.<br>"
                     "<em>Hızlı kontrol: Telefonunuzdan *#06# tuşlayın. Ekranda EID numarasını görüyorsanız eSIM destekleniyor demektir.</em>"
            },
            {
                "q": "🌐 eSIM ve QR kodu nedir?",
                "a": "<strong>eSIM</strong> gömülü ve tamamen dijital bir SIM karttır. Operatör ofislerine gitmeye gerek kalmadan çalışır.<br>"
                     "<strong>QR kodu</strong> dijital anahtarınızdır. Kamerayla tarattığınızda internet profilini otomatik olarak indirir."
            },
            {
                "q": "📲 BG eSIM'imi nasıl kurarım?",
                "a": "Kurulum için üç kolay yolunuz var:<br>"
                     "1. <strong>1 Tıkla (En hızlısı):</strong> Onay e-postasını telefonunuzdan açın ve işletim sisteminiz (iOS/Android) için olan düğmeye basın.<br>"
                     "2. <strong>QR Kod ile:</strong> E-postadaki QR kodunu telefonunuzun kamerasıyla taratın.<br>"
                     "3. <strong>Manuel Giriş:</strong> Düğmelerin altında bulunan 'SM-DP+ adresi' ve 'Aktivasyon Kodu' bilgilerini kopyalayıp ayarlara yapıştırın."
            },
            {
                "q": "🔄 Zaten bir eSIM yüklüyse başka bir tane ekleyebilir miyim?",
                "a": "Evet, kesinlikle! Telefonunuza birden fazla eSIM profili yükleyebilirsiniz (genellikle 5 ila 10 adet). Ayarlardan o anda hangi kartın aktif olacağını seçmeniz yeterlidir."
            },
            {
                "q": "⏳ eSIM kartı ne zaman satın almalıyım?",
                "a": "Satın alma işlemini seyahatinizden <strong>1-2 gün önce</strong> yapmanız en iyisidir. Evinizde Wi-Fi varken profili kurabilirsiniz. Paket, siz yurt dışına varana kadar veri tüketmez."
            },
            {
                "q": "📅 Paket geçerliliği ne zaman başlar?",
                "a": "Çoğu destinasyon için geçerlilik süresi ancak hedef ülkeye vardığınızda ve telefonunuz yerel ortak ağa bağlandığında başlar. Evde kurulum yapmak paket günlerinizden düşmez."
            },
            {
                "q": "🗺️ Aynı eSIM planını birden fazla ülkede kullanabilir miyim?",
                "a": "Belirli bir ülke için paket satın alırsanız sadece orada çalışır. Birden fazla ülkeden geçecekseniz, Bölgesel planlarımızdan birini seçin (örneğin 'Avrupa' planı)."
            },
            {
                "q": "📞 Aramalar ve SMS'ler için telefon numarası alıyor muyum?",
                "a": "eSIM paketlerimiz yalnızca mobil veri (Data-only) amaçlıdır. Geleneksel bir numara içermezler, ancak WhatsApp, Viber veya Telegram üzerinden ücretsiz görüşme yapabilirsiniz."
            },
            {
                "q": "📶 eSIM'im ile internet paylaşımı (HotSpot) yapabilir miyim?",
                "a": "<strong>Evet!</strong> Tüm eSIM kartlarımız internet paylaşımı (HotSpot / Tethering) işlevini destekler. Bağlantınızı dizüstü bilgisayarınız veya arkadaşlarınızla paylaşabilirsiniz."
            },
            {
                "q": "📴 eSIM kullanırsam mevcut SIM kartım çalışmaya devam edecek mi?",
                "a": "<strong>Evet, yerel SIM kartınız tamamen aktif kalır.</strong> Telefonunuz Çift SIM moduna geçer. eSIM size yurt dışında ucuz internet sağlarken, yerel numaranızdan arama almaya devam edersiniz."
            },
            {
                "q": "📊 Kalan verilerimi nasıl görebilirim?",
                "a": "Çok kolay! Satın alma işleminden sonra, kişisel kullanım sayfanızın bağlantısını içeren bir e-posta gönderiyoruz. Tek bir tıklamayla kalan verinizi görebilirsiniz."
            }
        ]
    },
    "es": {
        "title": "❓ Preguntas frecuentes (FAQ)",
        "subtitle": "Todo lo que necesitas saber sobre tus tarjetas eSIM de BG eSIM en un solo lugar.",
        "footer_title": "🚀 Consigue una eSIM de alta velocidad ahora",
        "footer_sub": "Viaja libremente sin costoso roaming y sin esperar en colas.",
        "items": [
            {
                "q": "📱 ¿Mi teléfono es compatible con eSIM?",
                "a": "La mayoría de los smartphones modernos son compatibles con la tecnología eSIM.<br>"
                     "• <strong>Para iPhone:</strong> Todos los de iPhone XS, XS Max, XR y posteriores.<br>"
                     "• <strong>Para Samsung:</strong> Series Galaxy S20, S21, S22, S23, S24, Note 20, Fold y Flip.<br>"
                     "• <strong>Para Google Pixel:</strong> Todos los de Pixel 3 y posteriores.<br>"
                     "<em>Comprobación rápida: Marca *#06# en tu teléfono. Si ves un número EID, tu teléfono es compatible con eSIM.</em>"
            },
            {
                "q": "🌐 ¿Qué es una eSIM y un código QR?",
                "a": "Una <strong>eSIM</strong> es una tarjeta SIM integrada y completamente digital. No necesitas visitar una tienda física ni cambiar chips.<br>"
                     "El <strong>código QR</strong> es tu llave digital. Al escanearlo con la cámara, tu dispositivo descarga el perfil de internet automáticamente."
            },
            {
                "q": "📲 ¿Cómo instalo mi eSIM de BG eSIM?",
                "a": "Tienes tres formas súper fáciles de instalarla:<br>"
                     "1. <strong>En 1 clic (La más rápida):</strong> Abre el correo de confirmación directamente desde tu teléfono y pulsa el botón correspondiente (iOS/Android).<br>"
                     "2. <strong>Mediante código QR:</strong> Escanea el código QR del correo con la cámara de tu teléfono.<br>"
                     "3. <strong>Entrada manual:</strong> Usa la 'Dirección SM-DP+' y el 'Código de activación' que te dejamos debajo de los botones en los ajustes de tu teléfono."
            },
            {
                "q": "🔄 Ya tengo una eSIM instalada, ¿puedo añadir otra?",
                "a": "¡Sí, por supuesto! Puedes tener varios perfiles eSIM instalados en tu teléfono (normalmente entre 5 y 10). Solo necesitas seleccionar cuál tarjeta deseas tener activa en cada momento."
            },
            {
                "q": "⏳ ¿Cuándo debo comprar una tarjeta eSIM?",
                "a": "Lo ideal es realizar la compra <strong>1 o 2 días antes de tu viaje</strong>. Puedes instalar el perfil cómodamente en casa con una conexión Wi-Fi estable. El paquete no consumirá datos hasta que llegues al extranjero."
            },
            {
                "q": "📅 ¿Cuándo empieza la validez del paquete?",
                "a": "Para la mayoría de los destinos, la validez comienza únicamente cuando llegas al país de destino y tu teléfono se conecta a la red asociada local. Instalarla en casa no reduce los días de tu paquete."
            },
            {
                "q": "🗺️ ¿Puedo usar el mismo plan eSIM en varios países?",
                "a": "Si compras un paquete para un país específico (por ejemplo, solo Grecia), solo funcionará allí. Si viajas por varios países, elige uno de nuestros planes regionales (como 'Europa')."
            },
            {
                "q": "📞 ¿Recibo un número de teléfono con llamadas y SMS?",
                "a": "Nuestros paquetes eSIM están diseñados exclusivamente para datos móviles (Data-only). No incluyen un número tradicional. Sin embargo, puedes realizar llamadas gratuitas ilimitadas a través de WhatsApp, Viber o Messenger."
            },
            {
                "q": "📶 ¿Puedo compartir internet (HotSpot) con mi eSIM?",
                "a": "<strong>¡Sí!</strong> Todas nuestras tarjetas eSIM admiten la función de compartir internet (HotSpot / Tethering). Puedes compartir fácilmente tu conexión con tu portátil o tableta."
            },
            {
                "q": "📴 Si uso eSIM, ¿seguirá funcionando mi tarjeta SIM actual?",
                "a": "<strong>Sí, tu tarjeta SIM habitual sigue estando totalmente activa.</strong> Tu teléfono pasa al modo 'Dual SIM'. Puedes recibir llamadas y SMS en tu número local mientras la eSIM te proporciona internet barato."
            },
            {
                "q": "📊 ¿Cómo puedo ver mis datos restantes?",
                "a": "¡Es muy fácil! Justo después de la compra, te enviamos un segundo correo con un enlace a tu página de consumo personal para ver tus datos en tiempo real."
            }
        ]
    }
}


def get_server_side_price(package_slug: str) -> Optional[float]:
    """
    Взима официалната цена от eSIM Access API по package_slug.
    Никога не се доверява на цената от frontend-а.
    Връща price_eur или None ако пакетът не е намерен.
    """
    try:
        location_code = package_slug.split("_")[0]
        data = get_packages(location=location_code)
        packages = data.get("obj", {}).get("packageList", [])
        for p in packages:
            if p.get("slug", "").upper() == package_slug.upper():
                original_price_usd = p["price"] / 10000
                price_eur = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)
                return price_eur
    except Exception as e:
        print(f"[PRICE CHECK] ❌ Грешка при вземане на цена за {package_slug}: {e}")
    return None


def process_webhook_data(event, base_url):
    """Тази функция обработва тежката логика на заден план, без да бави отговора към Stripe."""
    if event["type"] == "checkout.session.completed":
        raw_session = event["data"]["object"]
        session_id = raw_session["id"]

        if get_order_by_session(session_id):
            print(f"[BACKGROUND TASK] ℹ️ Сесията вече е обработена: {session_id}")
            return

        stripe_session = stripe.checkout.Session.retrieve(session_id)
        meta = dict(stripe_session.get("metadata") or {})

        print(f"[BACKGROUND TASK] 🔍 Metadata: {meta}")

        if not meta.get("package_slug"):
            print("[BACKGROUND TASK] ⚠️ Липсва package_slug в metadata!")
            return

        package_slug = meta.get("package_slug", "")
        full_name = meta.get("full_name", "")
        country = meta.get("country", "")
        duration = meta.get("duration", "")
        gb = meta.get("gb", "")
        lang = meta.get("lang", "en")
        promo_code_used = meta.get("promo_code_used", "").strip()
        customer_email = stripe_session.get("customer_email", "")
        amount_total = stripe_session.get("amount_total")
        order_amount = round(amount_total / 100, 2) if amount_total is not None else None

        qr_code_url = None
        iccid = None
        esim_tran_no = ""
        smdp_address = ""
        matching_id = ""
        lpa_string = ""
        affiliate_commission = None
        affiliate = None

        if promo_code_used:
            affiliate = get_affiliate_by_promo_code(promo_code_used)
            if affiliate and order_amount is not None:
                affiliate_commission = round(
                    order_amount * (float(affiliate["commission_percent"]) / 100),
                    2,
                )

        try:
            esim_result = order_esim(package_code=package_slug)
            qr_code_url = esim_result["qr_code_url"]
            iccid = esim_result["iccid"]
            esim_tran_no = esim_result.get("esim_tran_no", "")
            smdp_address = esim_result.get("smdp_address", "")
            matching_id = esim_result.get("matching_id", "")
            lpa_string = esim_result.get("lpa_string", "")
            print(f"[BACKGROUND TASK] ✅ eSIM купен: ICCID={iccid}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при купуване на eSIM: {e}")

        # 🍏🤖 ── СГЛОБЯВАНЕ НА UNIVERSAL LINKS (С МАЛКИ БУКВИ) ──

        ios_universal_link = ""
        android_universal_link = ""
        if lpa_string:
            # За Apple: Изискват изцяло малки букви, но оставяме символите $ и : чисти
            ios_universal_link = f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={lpa_string.lower()}"

            # За Android: Подаваме АБСОЛЮТНО СУРОВИЯ низ (LPA:1$...), с големи букви и без кодиране
            android_universal_link = f"https://esimsetup.android.com/esim_qrcode_provisioning?carddata={lpa_string}"
        # ────────────────────────────────────────────────────────
        # ────────────────────────────────────────────────────────

        try:
            save_order(
                stripe_session_id=session_id,
                full_name=full_name,
                email=customer_email,
                package_slug=package_slug,
                country=country,
                gb=gb,
                duration=duration,
                iccid=iccid or "",
                qr_code_url=qr_code_url or "",
                esim_tran_no=esim_tran_no,
                smdp_address=smdp_address,
                matching_id=matching_id,
                lang=lang,
                promo_code_used=promo_code_used,
                affiliate_commission=affiliate_commission,
                order_amount=order_amount,
                status="completed" if iccid else "esim_failed",
            )
            if affiliate and affiliate_commission is not None:
                update_affiliate_totals(
                    affiliate_id=affiliate["id"],
                    earned_delta=affiliate_commission,
                )
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при запис в БД: {e}")

        try:
            from app.utils.mailer import send_esim_email
            send_esim_email(
                to_email=customer_email,
                full_name=full_name,
                country=country,
                gb=gb,
                duration=duration,
                qr_code_url=qr_code_url,
                iccid=iccid,
                lang=lang,
                smdp_address=smdp_address,
                matching_id=matching_id,
                lpa_string=lpa_string,
                ios_link=ios_universal_link,  # 🍏 Нов параметър
                android_link=android_universal_link,  # 🤖 Нов параметър
            )
            print(f"[BACKGROUND TASK] 📧 Имейл 1 изпратен към: {customer_email}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при имейл 1: {e}")

        try:
            from app.utils.mailer import send_usage_email
            usage_url = base_url + f"usage/{iccid}"
            send_usage_email(
                to_email=customer_email,
                full_name=full_name,
                country=country,
                iccid=iccid or "",
                usage_url=usage_url,
                lang=lang,
            )
            print(f"[BACKGROUND TASK] 📧 Имейл 2 изпратен към: {customer_email}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при имейл 2: {e}")

        try:
            from app.utils.mailer import send_esim_email
            send_esim_email(
                to_email=settings.SUPPORT_EMAIL,
                full_name=f"🔔 НОВА ПОРЪЧКА от {full_name} ({customer_email})",
                country=country,
                gb=gb,
                duration=duration,
                qr_code_url=qr_code_url,
                iccid=iccid,
                lang="bg",
            )
            print(f"[BACKGROUND TASK] 📧 Admin известие изпратено към: {settings.SUPPORT_EMAIL}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при admin известие: {e}")

    else:
        print(f"[BACKGROUND TASK] ℹ️ Игнорирано събитие: {event['type']}")


# ─── WEBHOOK ПЪРВО — преди всякакъв middleware! ───────────────────────────────
@app.post("/webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    print(f"[WEBHOOK] 📥 Получен! bytes={len(payload)}, sig={sig_header[:30]}")

    if not sig_header:
        print("[WEBHOOK] ❌ Липсва Stripe-Signature header!")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature")

    if not payload:
        print("[WEBHOOK] ❌ Празен payload!")
        raise HTTPException(status_code=400, detail="Empty payload")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError as e:
        print(f"[WEBHOOK] ❌ Invalid payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    except stripe.SignatureVerificationError as e:
        print(f"[WEBHOOK] ❌ Invalid signature: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    print(f"[WEBHOOK] ✅ Валидиран event: {event['type']}. Прехвърляне на заден план...")

    base_url = str(request.base_url)
    background_tasks.add_task(process_webhook_data, event, base_url)

    return {"status": "accepted"}


# ─────────────────────────────────────────────────────────────────────────────


# ─── MIDDLEWARE (след webhook!) ───────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[REQUEST] {request.method} {request.url.path}")
    response = await call_next(request)
    print(f"[RESPONSE] {response.status_code}")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=PARTNER_SESSION_SECRET,
    session_cookie="partner_session",
    same_site="strict",
    https_only=APP_ENV != "development",
)
# ─────────────────────────────────────────────────────────────────────────────


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["urlencode"] = urllib.parse.quote
_request_counts: dict = defaultdict(list)


def rate_limit(ip: str, max_requests: int = 10, window: int = 60) -> bool:
    now = time.time()
    _request_counts[ip] = [
        t for t in _request_counts[ip]
        if now - t < window
    ]
    if len(_request_counts[ip]) >= max_requests:
        return True
    _request_counts[ip].append(now)
    return False


REGIONAL_KEYWORDS = {
    "europe", "asia", "africa",
    "north america", "south america", "latin america",
    "caribbean", "middle east", "oceania", "pacific",
    "balkans", "scandinavia", "nordic", "global",
}


def is_regional_package(name: str) -> bool:
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in REGIONAL_KEYWORDS)


def resolve_country_code(query: str) -> Optional[str]:
    if not query:
        return None
    q = query.strip()
    found = resolve_iso2_from_text(q)
    if found:
        return found
    if len(q) <= 3:
        country = pycountry.countries.get(alpha_2=q.upper())
        if country:
            return country.alpha_2
        country = pycountry.countries.get(alpha_3=q.upper())
        if country:
            return country.alpha_2
    try:
        results = pycountry.countries.search_fuzzy(q)
        if results:
            return results[0].alpha_2
    except LookupError:
        pass
    return None


def process_packages(raw: List[Dict[Any, Any]], lang: str = "en") -> Dict[str, List]:
    seen = set()
    filtered = []

    for p in raw:
        name = p.get("name", "")
        slug = p.get("slug", "").lower()
        duration = p.get("duration", 0)

        if slug in seen:
            continue
        seen.add(slug)

        if duration == 1:
            continue

        volume_gb = round(p.get("volume", 0) / (1024 ** 3), 1)
        if volume_gb < 1:
            continue

        if "nonhkip" in slug or "nonhkip" in name.lower():
            continue

        if is_regional_package(name):
            continue

        original_price_usd = p["price"] / 10000
        p["price_eur"] = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)

        location_code = p.get("locationCode", "")
        p["volume_gb"] = volume_gb
        p["country_name"] = translate_country(location_code, lang)

        filtered.append(p)

    groups: Dict[str, List] = {"7": [], "15": [], "30": [], "other": []}

    for p in filtered:
        d = p.get("duration", 0)
        if d == 7:
            groups["7"].append(p)
        elif d == 15:
            groups["15"].append(p)
        elif d == 30:
            groups["30"].append(p)
        else:
            groups["other"].append(p)

    for key in groups:
        groups[key].sort(key=lambda x: x["price_eur"])

    return groups


def make_lang_urls(request: Request, supported_langs: dict) -> dict:
    current_url = str(request.url.path)
    if request.query_params:
        current_url += "?" + str(request.query_params)
    lang_urls = {}
    for code in supported_langs:
        encoded = urllib.parse.quote(current_url, safe="")
        lang_urls[code] = f"/set-lang?lang={code}&redirect={encoded}"
    return lang_urls


def make_context(request: Request, lang: str, **kwargs) -> dict:
    return {
        "request": request,
        "lang": lang,
        "t": get_ui(lang),
        "supported_langs": SUPPORTED_LANGS,
        "lang_urls": make_lang_urls(request, SUPPORTED_LANGS),
        **kwargs,
    }


def get_authenticated_partner(request: Request) -> Optional[dict]:
    partner_id = request.session.get("partner_id")
    if not partner_id:
        return None
    return get_affiliate_by_id(partner_id)


def format_order_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def get_country_suggestions(lang: str) -> list:
    from app.translations import COUNTRY_TRANSLATIONS
    result = []
    for iso2, names in COUNTRY_TRANSLATIONS.items():
        name = names.get(lang) or names.get("en") or iso2
        result.append((iso2, name))
    return sorted(result, key=lambda x: x[1])


@app.get("/set-lang")
def set_lang(lang: str = "en", redirect: str = "/"):
    valid = list(SUPPORTED_LANGS.keys())
    if lang not in valid:
        lang = "en"
    response = RedirectResponse(url=redirect)
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(
        request, lang,
        groups=None,
        selected_country="",
        resolved_code=None,
        error=None,
        total=0,
        country_suggestions=get_country_suggestions(lang),
    )
    return templates.TemplateResponse("index.html", ctx)


@app.get("/search", response_class=HTMLResponse)
def search(
        request: Request,
        country: str = Query(""),
        lang: str = Cookie(default="en"),
):
    groups = None
    error = None
    resolved_code = None
    total = 0

    if country.strip():
        resolved_code = resolve_country_code(country.strip())
        if resolved_code:
            data = get_packages(location=resolved_code)
            raw_packages = data.get("obj", {}).get("packageList", [])
            groups = process_packages(raw_packages, lang=lang)
            total = sum(len(v) for v in groups.values())
        else:
            t = get_ui(lang)
            error = t["no_results"] + ": '" + country + "'"

    ctx = make_context(
        request, lang,
        groups=groups,
        selected_country=country,
        resolved_code=resolved_code,
        error=error,
        total=total,
        country_suggestions=get_country_suggestions(lang),
    )
    return templates.TemplateResponse("index.html", ctx)


@app.get("/instructions", response_class=HTMLResponse)
def instructions(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(request, lang)
    return templates.TemplateResponse("instructions.html", ctx)


@app.get("/contacts", response_class=HTMLResponse)
def contacts(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(
        request, lang,
        support_email=settings.SUPPORT_EMAIL,
        support_phone=settings.SUPPORT_PHONE,
    )
    return templates.TemplateResponse("contacts.html", ctx)


@app.get("/faq", response_class=HTMLResponse)
def faq(request: Request, lang: str = Cookie(default="en")):
    faq_content = FAQ_DATA.get(lang, FAQ_DATA["en"])

    # Подаваме празни стойности за променливите, които index.html изисква
    ctx = make_context(
        request, lang,
        faq_title=faq_content["title"],
        faq_subtitle=faq_content["subtitle"],
        faq_footer_title=faq_content["footer_title"],
        faq_footer_sub=faq_content["footer_sub"],
        faq_items=faq_content["items"],
        support_email=settings.SUPPORT_EMAIL,

        # 💡 ТУК Е СПАСЕНИЕТО: Залъгваме index.html, че няма търсени пакети в момента
        groups=None,
        selected_country="",
        resolved_code=None,
        error=None,
        total=0,
        country_suggestions=get_country_suggestions(lang)
    )
    return templates.TemplateResponse("faq.html", ctx)


@app.get("/checkout", response_class=HTMLResponse)
def checkout(
        request: Request,
        package_slug: str = Query(""),
        country: str = Query(""),
        duration: int = Query(0),
        gb: float = Query(0.0),
        price_eur: float = Query(0.0),
        lang: str = Cookie(default="en"),
):
    ctx = make_context(
        request, lang,
        package_slug=package_slug,
        country=country,
        duration=duration,
        gb=gb,
        price_eur=price_eur,
    )
    return templates.TemplateResponse("checkout.html", ctx)


@app.get("/balance")
def balance():
    data = check_balance()
    balance_usd = data["obj"]["balance"] / 100
    return {
        "balance_cents": data["obj"]["balance"],
        "balance_usd": f"${balance_usd:.2f}"
    }


@app.post("/pay")
async def pay(
        request: Request,
        full_name: str = Form(...),
        email: str = Form(...),
        confirm_email: str = Form(...),
        package_slug: str = Form(...),
        country: str = Form(...),
        duration: int = Form(...),
        gb: float = Form(...),
        promo_code: Optional[str] = Form(default=None),
        lang: str = Cookie(default="en"),
):
    ip = request.client.host
    if rate_limit(ip, max_requests=5, window=60):
        raise HTTPException(status_code=429, detail="Твърде много заявки. Моля, изчакайте една минута.")

    # ── Проверка дали двата имейла съвпадат ──────────────────────────────────
    if email.strip().lower() != confirm_email.strip().lower():
        raise HTTPException(status_code=400, detail="Имейл адресите трябва да бъдат еднакви.")
    # ─────────────────────────────────────────────────────────────────────────

    # ── ЗАЩИТА: Цената се изчислява САМО от сървъра — frontend стойността се игнорира ──
    location_code = package_slug.split("_")[0]
    try:
        data = get_packages(location=location_code)
        packages = data.get("obj", {}).get("packageList", [])
    except Exception as e:
        print(f"[PAY] ❌ Грешка при извличане на пакети за {location_code}: {e}")
        raise HTTPException(status_code=503, detail="Временна грешка. Моля, опитайте отново.")

    server_price: Optional[float] = None
    for p in packages:
        if p.get("slug", "").upper() == package_slug.upper():
            original_price_usd = p["price"] / 10000
            server_price = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)
            break

    if server_price is None:
        print(f"[PAY] ❌ Пакетът не е намерен: {package_slug}")
        raise HTTPException(status_code=400, detail="Невалиден пакет. Моля, опитайте отново.")

    amount_cents = int(round(server_price * 100))
    print(f"[PAY] ✅ Цена изчислена от сървъра: €{server_price} ({amount_cents} цента) за {package_slug}")
    # ─────────────────────────────────────────────────────────────────────────

    normalized_promo_code = (promo_code or "").strip().upper()
    checkout_discounts = None
    if normalized_promo_code:
        promotion_codes = stripe.PromotionCode.list(
            code=normalized_promo_code,
            active=True,
            limit=1,
        ).get("data", [])
        if not promotion_codes:
            raise HTTPException(status_code=400, detail=get_ui(lang)["invalid_promo_code"])
        checkout_discounts = [{"promotion_code": promotion_codes[0]["id"]}]

    session_kwargs = dict(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": amount_cents,
                "product_data": {
                    "name": f"eSIM {country} {gb}GB {duration} days",
                    "description": f"Package: {package_slug}",
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        customer_email=email,
        metadata={
            "full_name": full_name,
            "package_slug": package_slug,
            "country": country,
            "duration": str(duration),
            "gb": str(gb),
            "promo_code_used": normalized_promo_code,
            "lang": lang,
        },
        success_url=str(request.base_url) + "success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=str(request.base_url) + "cancel",
    )
    if checkout_discounts:
        session_kwargs["discounts"] = checkout_discounts

    session = stripe.checkout.Session.create(**session_kwargs)

    return RedirectResponse(url=session.url, status_code=303)


@app.get("/success", response_class=HTMLResponse)
def success(
        request: Request,
        session_id: str = Query(""),
        lang: str = Cookie(default="en"),
):
    ctx = make_context(request, lang, session_id=session_id)
    return templates.TemplateResponse("success.html", ctx)


@app.get("/cancel", response_class=HTMLResponse)
def cancel(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(request, lang)
    return templates.TemplateResponse("cancel.html", ctx)


@app.get("/test-email")
def test_email(secret: str = Query("")):
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=404, detail="Not found")
    if secret != settings.TEST_EMAIL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.utils.mailer import send_esim_email
    send_esim_email(
        to_email="test@test.com",
        full_name="Test User",
        country="Germany",
        gb="3",
        duration="7",
        qr_code_url="https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=TestQR",
        iccid="89359999999999999",
        lang="bg",
    )
    return {"status": "✅ Имейлът е изпратен! Провери пощата."}


@app.get("/admin", response_class=HTMLResponse)
def admin_login(request: Request, lang: str = Cookie(default="en")):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin", response_class=HTMLResponse)
def admin_login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
):
    if (
            username != settings.ADMIN_USER or
            password != settings.ADMIN_PASSWORD
    ):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Грешни данни!"},
            status_code=401,
        )
    # ── ЗАЩИТА: записваме фиксиран низ в бисквитката, НЕ паролата ────────────
    response = RedirectResponse(url="/admin/orders", status_code=303)
    response.set_cookie(
        key="admin_auth",
        value=ADMIN_SESSION_VALUE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response
    # ─────────────────────────────────────────────────────────────────────────


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(
        request: Request,
        admin_auth: str = Cookie(default=""),
        status_filter: str = Query(default="all"),
        q: Optional[str] = Query(default=None),
):
    if admin_auth != ADMIN_SESSION_VALUE:
        return RedirectResponse(url="/admin", status_code=303)

    # 1. Взимаме абсолютно всички поръчки
    all_orders = get_all_orders(status_filter=None)

    # 2. Броим ги точно, за да работят квадратчетата най-горе
    total = len(all_orders)
    completed = sum(1 for o in all_orders if o.get("status") == "completed")
    failed = sum(1 for o in all_orders if o.get("status") == "esim_failed")

    # 3. Подготвяме списъка, който реално ще покажем в таблицата
    orders_to_show = all_orders

    # Ако е избран филтър за статус от падащото меню:
    if status_filter != "all":
        orders_to_show = [o for o in orders_to_show if o.get("status") == status_filter]

    # Ако си написал нещо в търсачката:
    if q and q.strip():
        search_query = q.strip().lower()
        orders_to_show = [
            o for o in orders_to_show
            if search_query in str(o.get("full_name", "")).lower()
               or search_query in str(o.get("email", "")).lower()
               or search_query in str(o.get("iccid", "")).lower()
        ]

    # 4. Пращаме всичко готово към сайта
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "orders": orders_to_show,
            "status_filter": status_filter,
            "q": q,
            "total": total,
            "completed": completed,
            "failed": failed,
        },
    )


@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie("admin_auth")
    return response


@app.get("/partner/login", response_class=HTMLResponse)
def partner_login(request: Request):
    if get_authenticated_partner(request):
        return RedirectResponse(url="/partner/dashboard", status_code=303)
    return templates.TemplateResponse("partner_login.html", {"request": request})


@app.post("/partner/login", response_class=HTMLResponse)
def partner_login_post(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
):
    affiliate = get_affiliate_by_email(email)
    if not affiliate or not PASSWORD_CONTEXT.verify(password, affiliate["hashed_password"]):
        return templates.TemplateResponse(
            "partner_login.html",
            {"request": request, "error": "Грешен имейл или парола."},
            status_code=401,
        )

    request.session.clear()
    request.session["partner_id"] = affiliate["id"]
    return RedirectResponse(url="/partner/dashboard", status_code=303)


@app.get("/partner/dashboard", response_class=HTMLResponse)
def partner_dashboard(request: Request):
    affiliate = get_authenticated_partner(request)
    if not affiliate:
        return RedirectResponse(url="/partner/login", status_code=303)

    orders = [
        {**order, "created_at_display": format_order_datetime(order.get("created_at", ""))}
        for order in get_orders_by_promo_code(affiliate["promo_code"])
    ]
    total_earned = float(affiliate.get("total_earned") or 0)
    total_paid = float(affiliate.get("total_paid") or 0)
    payout_due = max(total_earned - total_paid, 0.0)

    return templates.TemplateResponse(
        "partner_dashboard.html",
        {
            "request": request,
            "affiliate": affiliate,
            "orders": orders,
            "total_sales": len(orders),
            "total_earned": total_earned,
            "payout_due": payout_due,
        },
    )


@app.post("/partner/logout")
def partner_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/partner/login", status_code=303)


@app.get("/usage/{iccid}", response_class=HTMLResponse)
def usage_page(
        request: Request,
        iccid: str,
        lang: str = Cookie(default="en"),
):
    usage_data = None
    error = None

    try:
        usage_data = query_esim_usage(iccid=iccid, lang=lang)
        if (
            usage_data
            and usage_data.get("not_active")
            and get_order_by_iccid(iccid)
            and not get_esim_tran_no_by_iccid(iccid)
        ):
            usage_data["remaining"] = get_ui(lang)["legacy_order_support"]
    except Exception as e:
        error = str(e)

    ctx = make_context(
        request, lang,
        iccid=iccid,
        usage_data=usage_data,
        error=error,
    )
    return templates.TemplateResponse("usage.html", ctx)


@app.get("/sitemap.xml")
def get_sitemap(request: Request):
    base_url = str(request.base_url).rstrip("/")

    urls = [
        f"{base_url}/",
        f"{base_url}/instructions",
        f"{base_url}/contacts",
        f"{base_url}/admin",
    ]

    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in urls:
        sitemap_xml += f"  <url>\n    <loc>{url}</loc>\n    <changefreq>daily</changefreq>\n  </url>\n"

    sitemap_xml += "</urlset>"

    return Response(content=sitemap_xml, media_type="application/xml")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
