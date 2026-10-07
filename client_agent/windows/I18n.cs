// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.Serialization.Json;

namespace HeimserverClient {
    public static class I18n {
        static readonly Dictionary<string,string> English = Load();
        public static string Language(CultureInfo culture) {
            return culture != null && culture.TwoLetterISOLanguageName == "de" ? "de" : "en";
        }
        static Dictionary<string,string> Load() {
            using(var input = typeof(I18n).Assembly.GetManifestResourceStream("hsm.client_en.json")) {
                if(input == null) throw new InvalidOperationException("Client language resource is missing.");
                var serializer = new DataContractJsonSerializer(typeof(Dictionary<string,string>), new DataContractJsonSerializerSettings { UseSimpleDictionaryFormat = true });
                return (Dictionary<string,string>)serializer.ReadObject(input);
            }
        }
        public static string Tr(string source) {
            string translated;
            return Language(CultureInfo.CurrentUICulture) == "de" || !English.TryGetValue(source, out translated) ? source : translated;
        }
    }
}
